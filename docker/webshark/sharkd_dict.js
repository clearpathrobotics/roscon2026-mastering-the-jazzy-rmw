/* sharkd_dict.js
 *
 * Copyright (C) 2016 Jakub Zawadzki
 * Copyright (C) 2020 QXIP B.V.
 * Copyright (C) 2026 Rockwell Automation, Inc.
 *
 * A modified version of api/custom_module/sharkd_dict.js from QXIP/node-webshark, taken at
 * commit 4615493c36c5020592700b06198b3f9188556e99. That snapshot is GPL-2.0-or-later; the
 * AGPL-3.0 shown on the project's GitHub page today came later and does not apply to it.
 * Changes are listed in docker/webshark/THIRD-PARTY.md in the workshop repository, and in
 * /usr/src/node-webshark/THIRD-PARTY.md inside the image.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

const {PromiseSocket} = require('promise-socket');
const { spawn } = require('child_process');
const fs = require('fs');

const SHARKD_SOCKET = process.env.SHARKD_SOCKET || "/var/run/sharkd.sock";
const CAPTURES_PATH = process.env.CAPTURES_PATH || "/captures/";
var sharkd_objects = {};
var AsyncLock = require('async-lock');
var lock = new AsyncLock({timeout: 300000}); // 5 minutes timeout for the lock
var sharkd_proc = null;
const sleep = (waitTimeInMs) => new Promise(resolve => setTimeout(resolve, waitTimeInMs));

// ---- sharkd 4.x JSON-RPC 2.0 compatibility shim -------------------------
// qxip/webshark was written for the sharkd 3.x request/response format.
// sharkd 4.x uses JSON-RPC 2.0 on the socket and changed a few payload shapes.
// These two helpers translate between the formats so the rest of the app is unchanged.

let _rpc_id = 1;
const _NUMERIC_FIELDS = new Set(['skip', 'limit', 'frame', 'col', 'i', 'interval']);

function _to_jsonrpc(request) {
  const method = request.req;
  const params = {};
  for (const [k, v] of Object.entries(request)) {
    if (k === 'req') continue;
    // sharkd 4.x rejects prev_frame whatever the JSON type; it is only a
    // "previous frame" hint, so drop it.
    if (k === 'prev_frame') continue;
    if (k === 'capture') {
      // 'capture' routes the node app to the right socket; for load requests it
      // also needs to become the 'file' param that sharkd 4.x expects
      if (method === 'load') {
        const rel = v.startsWith('/') ? v.substr(1) : v;
        params.file = CAPTURES_PATH + rel;
      }
      continue;
    }
    if (_NUMERIC_FIELDS.has(k) && typeof v === 'string') {
      params[k] = parseInt(v, 10);
    } else if (v === 'true') {
      params[k] = true;
    } else if (v === 'false') {
      params[k] = false;
    } else if (v === 'yes') {
      params[k] = true;
    } else if (v === 'no') {
      params[k] = false;
    } else {
      params[k] = v;
    }
  }
  return { jsonrpc: '2.0', method, params, id: _rpc_id++ };
}

function _from_jsonrpc(data, method) {
  let r;
  try { r = JSON.parse(data); } catch (e) { return data; }
  if (!r || r.jsonrpc !== '2.0') return data; // not JSON-RPC, pass through

  if (r.error) {
    return JSON.stringify({ err: 1, errstr: (r.error.message || 'sharkd error') });
  }

  const result = r.result;

  // frames must stay unwrapped: the frontend's fetchColumns iterates the raw array.
  if (Array.isArray(result)) {
    if (method === 'frames') {
      return JSON.stringify(result);
    }
    return JSON.stringify({ frames: result, matched: result.length });
  }

  // load: sharkd 4.x returns {"status":"OK"} instead of {"err":0}
  if (result && result.status === 'OK') {
    return JSON.stringify({ err: 0 });
  }

  return JSON.stringify(result !== undefined ? result : {});
}
// --------------------------------------------------------------------------

get_loaded_sockets = function() {
  let return_array = [];
  Object.keys(sharkd_objects).forEach(function(socket_name){
    if (sharkd_objects[socket_name].stream.readable) {
      return_array.push(socket_name);
    } else {
      sharkd_objects[socket_name].destroy();
      delete sharkd_objects[socket_name];
    }
  });
  return return_array;
}

get_sharkd_cli = async function(capture) {
  let socket_name = capture.replace(CAPTURES_PATH,"");
  if (socket_name.startsWith("/")) {
    socket_name = socket_name.substr(1);
  }
  if (socket_name in sharkd_objects) { // return existing socket
    if (sharkd_objects[socket_name].stream.readable === false) {
      sharkd_objects[socket_name].destroy();
      delete sharkd_objects[socket_name];
      return get_sharkd_cli(capture);
    }
    return sharkd_objects[socket_name];
  } else { // no socket for this capture, create new one
    let new_socket = new PromiseSocket();
    new_socket.setTimeout(300000); // 5 minutes timeout per socket connection
    new_socket.stream.setEncoding('utf8');
    try {
      await new_socket.connect(SHARKD_SOCKET);
    }
    catch(err) {
      console.log("Error trying to connect to " + SHARKD_SOCKET)
      console.log(err);
      if (sharkd_proc !== null && sharkd_proc.pid) {
        console.log("sharkd_proc.pid: " + sharkd_proc.pid)
        sharkd_proc.kill('SIGHUP');
        await sleep(250);
        sharkd_proc = null;
      }
      try {
        console.log(`Trying to spawn unix:${SHARKD_SOCKET}`)
        try { fs.unlinkSync(SHARKD_SOCKET); } catch (_) {}
        sharkd_proc = spawn('sharkd', ['unix:' + SHARKD_SOCKET]);
        // sharkd 4.x daemonizes and the parent exits immediately, so wait for the socket to appear
        let _waited = 0;
        while (!fs.existsSync(SHARKD_SOCKET) && _waited < 2000) {
          await sleep(100);
          _waited += 100;
        }
        if (!fs.existsSync(SHARKD_SOCKET)) {
          console.log(`Error spawning sharkd under ${SHARKD_SOCKET}`);
          process.exit(1);
        }
      } catch (err_2) {
        console.log(`Error spawning sharkd under ${SHARKD_SOCKET}`);
        console.log(err_2);
        process.exit(1);
      }
      return get_sharkd_cli(capture);
    }
    sharkd_objects[socket_name] = new_socket;

    if(capture !== '') {
      await send_req({'req':'load', 'file': capture}, sharkd_objects[socket_name]);
      return sharkd_objects[socket_name];
    } else {
      return sharkd_objects[socket_name];
    }
  }
}

function _str_is_json(str) {
  try {
    var json = JSON.parse(str);
    return (typeof json === 'object');
  } catch (e) {
    return false;
  }
}

send_req = async function(request, sock) {
  let cap_file = '';

  if ("capture" in request) {
    if (request.capture.includes('..')) {
      return JSON.stringify({"err": 1, "errstr": "Nope"});
    }

    let req_capture = request.capture;

    if (req_capture.startsWith("/")) {
      req_capture = req_capture.substr(1);
    }

    /* Build from the leading-slash-stripped name, not the raw one. cap_file is the key
       lock.acquire() serialises on, while get_sharkd_cli() strips CAPTURES_PATH off it to
       pick the socket. Using the raw name, "x.pcap" and "/x.pcap" produce two lock keys
       ("/captures/x.pcap" and "/captures//x.pcap") that resolve to one sharkd socket, so
       the two requests interleave writes and reads on it. existsSync hides this, because
       the kernel collapses the double slash. */
    cap_file = `${CAPTURES_PATH}${req_capture}`;

    // verify that pcap exists
    if (fs.existsSync(cap_file) === false) {
        return JSON.stringify({"err": 1, "errstr": "Nope"});
    }
  }

  async function _send_req_internal() {
    let new_sock = sock;
    if (typeof(new_sock) === 'undefined') {
      new_sock = await get_sharkd_cli(cap_file);
    }

    if (new_sock === null) {
      return JSON.stringify({"err": 1, "errstr": `cannot connect to sharkd using socket: ${SHARKD_SOCKET}`});
    }
    try {
      await new_sock.write(JSON.stringify(_to_jsonrpc(request))+"\n");
    } catch (err) {
      console.log("Error writing to sharkd socket")
      console.log(err)
      return null;
    }

    let data = '';
    let chunk = await new_sock.read();

    data += chunk;
    while (_str_is_json(data) === false) {
      chunk = await new_sock.read();
      data += chunk;
    }

    return _from_jsonrpc(data, request.req);
  }

  return await lock.acquire(cap_file, _send_req_internal);
}

exports.get_sharkd_cli = get_sharkd_cli;
exports.send_req = send_req;
exports.get_loaded_sockets = get_loaded_sockets;
