#include "mock_robot_hardware/mock_robot_hardware.hpp"

#include <algorithm>

#include "hardware_interface/types/hardware_interface_type_values.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace mock_robot_hardware
{
hardware_interface::CallbackReturn MockRobotHardware::on_init(
  const hardware_interface::HardwareInfo & info)
{
  if (hardware_interface::SystemInterface::on_init(info) !=
    hardware_interface::CallbackReturn::SUCCESS)
  {
    return hardware_interface::CallbackReturn::ERROR;
  }

  if (info_.joints.size() != kWheelCount) {
    return hardware_interface::CallbackReturn::ERROR;
  }

  for (std::size_t i = 0; i < kWheelCount; ++i) {
    joint_names_[i] = info_.joints[i].name;
  }

  position_.fill(0.0);
  velocity_.fill(0.0);
  velocity_command_.fill(0.0);

  return hardware_interface::CallbackReturn::SUCCESS;
}

std::vector<hardware_interface::StateInterface> MockRobotHardware::export_state_interfaces()
{
  std::vector<hardware_interface::StateInterface> state_interfaces;
  state_interfaces.reserve(kWheelCount * 2);

  for (std::size_t i = 0; i < kWheelCount; ++i) {
    state_interfaces.emplace_back(
      joint_names_[i],
      hardware_interface::HW_IF_POSITION,
      &position_[i]);
    state_interfaces.emplace_back(
      joint_names_[i],
      hardware_interface::HW_IF_VELOCITY,
      &velocity_[i]);
  }

  return state_interfaces;
}

std::vector<hardware_interface::CommandInterface> MockRobotHardware::export_command_interfaces()
{
  std::vector<hardware_interface::CommandInterface> command_interfaces;
  command_interfaces.reserve(kWheelCount);

  for (std::size_t i = 0; i < kWheelCount; ++i) {
    command_interfaces.emplace_back(
      joint_names_[i],
      hardware_interface::HW_IF_VELOCITY,
      &velocity_command_[i]);
  }

  return command_interfaces;
}

hardware_interface::CallbackReturn MockRobotHardware::on_activate(
  const rclcpp_lifecycle::State &)
{
  std::fill(velocity_.begin(), velocity_.end(), 0.0);
  std::fill(velocity_command_.begin(), velocity_command_.end(), 0.0);
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::CallbackReturn MockRobotHardware::on_deactivate(
  const rclcpp_lifecycle::State &)
{
  std::fill(velocity_.begin(), velocity_.end(), 0.0);
  std::fill(velocity_command_.begin(), velocity_command_.end(), 0.0);
  return hardware_interface::CallbackReturn::SUCCESS;
}

hardware_interface::return_type MockRobotHardware::read(
  const rclcpp::Time &,
  const rclcpp::Duration & period)
{
  const double dt = period.seconds();

  for (std::size_t i = 0; i < kWheelCount; ++i) {
    velocity_[i] = velocity_command_[i];
    position_[i] += velocity_[i] * dt;
  }

  return hardware_interface::return_type::OK;
}

hardware_interface::return_type MockRobotHardware::write(
  const rclcpp::Time &,
  const rclcpp::Duration &)
{
  return hardware_interface::return_type::OK;
}
}  // namespace mock_robot_hardware

PLUGINLIB_EXPORT_CLASS(
  mock_robot_hardware::MockRobotHardware,
  hardware_interface::SystemInterface)
