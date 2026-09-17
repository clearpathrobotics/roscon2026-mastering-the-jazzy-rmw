#ifndef MOCK_ROBOT_HARDWARE__MOCK_ROBOT_HARDWARE_HPP_
#define MOCK_ROBOT_HARDWARE__MOCK_ROBOT_HARDWARE_HPP_

#include <array>
#include <string>
#include <vector>

#include "hardware_interface/system_interface.hpp"
#include "rclcpp_lifecycle/state.hpp"

namespace mock_robot_hardware
{
class MockRobotHardware : public hardware_interface::SystemInterface
{
public:
  hardware_interface::CallbackReturn on_init(
    const hardware_interface::HardwareInfo & info) override;

  std::vector<hardware_interface::StateInterface> export_state_interfaces() override;

  std::vector<hardware_interface::CommandInterface> export_command_interfaces() override;

  hardware_interface::CallbackReturn on_activate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::CallbackReturn on_deactivate(
    const rclcpp_lifecycle::State & previous_state) override;

  hardware_interface::return_type read(
    const rclcpp::Time & time,
    const rclcpp::Duration & period) override;

  hardware_interface::return_type write(
    const rclcpp::Time & time,
    const rclcpp::Duration & period) override;

private:
  static constexpr std::size_t kWheelCount = 4;
  std::array<std::string, kWheelCount> joint_names_;
  std::array<double, kWheelCount> position_{};
  std::array<double, kWheelCount> velocity_{};
  std::array<double, kWheelCount> velocity_command_{};
};
}  // namespace mock_robot_hardware

#endif  // MOCK_ROBOT_HARDWARE__MOCK_ROBOT_HARDWARE_HPP_
