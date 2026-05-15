#ifndef BASE_CONTROLLER_H
#define BASE_CONTROLLER_H

#include "rclcpp/rclcpp.hpp"

#include <string>
#include <iostream>

typedef union
{
  float value;
  unsigned char buf[4];
}UNION_FLOAT_TYPE;

#endif // BASE_CONTROLLER_H