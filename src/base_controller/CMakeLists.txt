cmake_minimum_required(VERSION 3.8)
project(base_controller)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# ROS 依赖
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)

# Nav2 依赖
find_package(nav2_core REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(nav2_controller REQUIRED)
find_package(nav2_costmap_2d REQUIRED)

# 手动链接serial库（关键：指定手动编译的库路径）
include_directories(
  include
  /usr/local/include  # serial库头文件路径
)
link_directories(/usr/local/lib)  # serial库so文件路径

# 编译节点
add_executable(base_controller_node src/base_controller.cpp)

ament_target_dependencies(base_controller_node
  rclcpp
  rclcpp_action
  tf2
  tf2_ros
  geometry_msgs
  nav_msgs
  sensor_msgs
  nav2_core
  nav2_msgs
  nav2_controller
  nav2_costmap_2d
)

# 链接serial库（手动编译的libserial.so）
target_link_libraries(base_controller_node 
  serial  # 手动编译的serial库
  pthread # serial库依赖线程库，必须加
)

# 安装可执行文件
install(TARGETS base_controller_node
  DESTINATION lib/${PROJECT_NAME})

# 安装头文件（到include目录，非share）
install(DIRECTORY include/
  DESTINATION include/${PROJECT_NAME})

# 安装参数/地图/启动/RViz文件（仅保留必要目录，删除src/include）
install(DIRECTORY param/ maps/ launch/ rviz/
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()