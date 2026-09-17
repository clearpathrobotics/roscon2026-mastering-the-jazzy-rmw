/* root.js
 *
 * Copyright (C) 2016 Jakub Zawadzki
 * Copyright (C) 2020 QXIP B.V.
 * Copyright (C) 2026 Rockwell Automation, Inc.
 *
 * A modified version of api/services/root.js from QXIP/node-webshark, taken at commit
 * 4615493c36c5020592700b06198b3f9188556e99. That snapshot is GPL-2.0-or-later; the
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

'use strict'
const fs = require('fs');
const fetch = require("node-fetch");
const sharkd_dict = require('../custom_module/sharkd_dict');
const CAPTURES_PATH = process.env.CAPTURES_PATH || "/captures/";

/* Stock webshark listed only *.pcap, which hides most captures a user actually arrives with:
   tshark -w and Wireshark's own Save both default to pcapng, and .cap is what a lot of vendor
   tooling emits. Verified in this image that sharkd reads .pcapng, .cap and gzipped variants
   at 200/200 frames each, so the filter was hiding files it could already open. Still an
   allow-list rather than "show everything", because /captures also holds the demo's own .csv
   and .png output. */
const CAPTURE_EXTENSIONS = ['.pcap', '.pcapng', '.cap'];

const is_capture_file = function(name) {
  const lower = name.toLowerCase().replace(/\.gz$/, '');
  return CAPTURE_EXTENSIONS.some(function(ext) { return lower.endsWith(ext); });
}

// Feeds the file list's Description column. index.html's WSCaptureFilesTable already renders
// file['desc'] when present. It just never had anything to read. Keyed by fixture name with
// no extension, since that is the one thing both a bare .pcap and a gzipped .pcap.gz agree on.
const fixture_name = function(pcap_file) {
  return pcap_file.replace(/\.gz$/i, '').replace(/\.(pcap|pcapng|cap)$/i, '');
}

const fixture_descriptions = (function() {
  const map = new Map();
  try {
    const text = fs.readFileSync(__dirname + '/fixture-descriptions.tsv', 'utf8');
    for (const line of text.split('\n')) {
      if (!line || line.startsWith('#')) continue;
      const tab = line.indexOf('\t');
      if (tab < 0) continue;
      const name = line.slice(0, tab).trim();
      if (name === 'fixture') continue;
      map.set(name, line.slice(tab + 1).trim());
    }
  } catch (err) {
    // No descriptions shipped for this build. The column just stays empty.
  }
  return map;
})();

const download = function(url, dest, cb) {
  var file = fs.createWriteStream(dest);
  var request = http.get(url, function(response) {
    response.pipe(file);
    file.on('finish', function() {
      file.close(cb);  // close() is async, call cb after close completes.
    });
  });
}


module.exports = function (fastify, opts, next) {

  fastify.register(require('fastify-static'), {
    root: CAPTURES_PATH,
    prefix: '/webshark//', // defeat unique prefix
  })

  fastify.get('/webshark/json', function (request, reply) {

    if (request.query && "req" in request.query) {
      if (request.query.req === 'files') {
        let files = fs.readdirSync(CAPTURES_PATH);
        let results = {"files":[], "pwd": "."};
        let loaded_files = sharkd_dict.get_loaded_sockets();
        files.forEach( async function(pcap_file){
          if (is_capture_file(pcap_file)) {

	    if(pcap_file.startsWith('http:')){
		  const res = await fetch(pcap_file);
                  var filename = pcap_file.split('/').pop()
		  const fileStream = fs.createWriteStream(CAPTURES_PATH+filename);
		  await new Promise((resolve, reject) => {
		      res.body.pipe(fileStream);
		      res.body.on("error", reject);
		      fileStream.on("finish", resolve);
		    });
		  pcap_file=filename;
	    }

            let pcap_stats = fs.statSync(CAPTURES_PATH + pcap_file);
            let desc = fixture_descriptions.get(fixture_name(pcap_file));
            if (loaded_files.includes(pcap_file)) {
              results.files.push({"name": pcap_file, "size": pcap_stats.size, "mtime": pcap_stats.mtimeMs, "status": {"online": true}, "desc": desc});
            } else {
              results.files.push({"name": pcap_file, "size": pcap_stats.size, "mtime": pcap_stats.mtimeMs, "desc": desc});
            }
          }
        });
        reply.send(JSON.stringify(results));
      } else if (request.query.req === 'download') {
        if ("capture" in request.query) {
          if (request.query.capture.includes('..')) {
            reply.send(JSON.stringify({"err": 1, "errstr": "Nope"}));
          }

          let cap_file = request.query.capture;
          if (cap_file.startsWith("/")) {
            cap_file = cap_file.substr(1);
          }

          if ("token" in request.query) {
            if (request.query.token === "self") {
              reply.header('Content-disposition', 'attachment; filename=' + cap_file);
              reply.sendFile(cap_file);
              next();
            } else {
              sharkd_dict.send_req(request.query).then((data) => {
                try {
                  data = JSON.parse(data);
                  reply.header('Content-Type', data.mime);
                  reply.header('Content-disposition', 'attachment; filename="' + data.file + '"');
                  let buff = new Buffer(data.data, 'base64');
                  reply.send(buff);
                } catch (err) {
                  reply.send(JSON.stringify({"err": 1, "errstr": "Nope"}));
                }
              });
            }
          } else {
            reply.send(JSON.stringify({"err": 1, "errstr": "Nope"}));
          }
        }
      } else if (
        request.query.req === 'tap' &&
        'tap0' in request.query &&
        ['srt:dcerpc', 'srt:rpc', 'srt:scsi', 'rtd:megaco'].includes(request.query.tap0) // catch the four invalid requests and prevent socket failure
      ) {
        reply.send(null);
      } else {
        sharkd_dict.send_req(request.query).then((data) => {
          reply.send(data);
        });
      }
    }
  })

  next()
}
