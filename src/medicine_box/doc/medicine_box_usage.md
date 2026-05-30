# 药盒功能使用说明

`medicine_box` 是药盒舵机控制包，目标是让 ROSA 或其它 ROS 2 节点通过服务接口指定药物名称，然后药盒舵机转到对应药格位置。

当前设计规则：

```text
每个药物绑定一个 slot
每个 slot 间隔 90 度

slot 0 -> 0 度
slot 1 -> 90 度
slot 2 -> 180 度
slot 3 -> 270 度
```

当前按 360 度电机/舵机预留映射，目标角度范围为 0-360 度。

## 包结构

```text
src/medicine_box/
  config/medicines.yaml                 药物和药格绑定配置
  launch/medicine_box.launch.py         药盒节点启动文件
  medicine_box/medicine_box_node.py     药盒节点源码
  doc/medicine_box_usage.md             本说明文档
```

## 硬件说明

本包参考 RDK X5 官方 PWM 示例，底层使用：

```python
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
p = Hobot.GPIO.PWM(pin, 50)
p.ChangeDutyCycle(initial_duty)
p.start(initial_duty)
```

注意：RDK 官方 PWM 示例没有在创建 `GPIO.PWM(...)` 前调用
`GPIO.setup(pin, GPIO.OUT)`。对 `Hobot.GPIO` 来说，PWM 引脚应直接创建
`GPIO.PWM`，否则可能先按普通 GPIO 占用该通道，再申请 PWM 时出现
`This channel is in use`。

另一个关键点是初始化顺序必须先 `ChangeDutyCycle(initial_duty)`，再
`start(initial_duty)`。不要先 `start(...)` 后 `ChangeDutyCycle(...)`。

运行实机前需要确认：

```text
1. 已通过 srpi-config 启用对应 PWM 组
2. 舵机信号线接到 launch 参数 pwm_pin 指定的 40pin 引脚
3. 舵机供电满足电流需求
4. 舵机电源 GND 和 RDK 板子 GND 共地
```

默认参数：

```text
pwm_pin=33
min_angle=0.0
max_angle=360.0
initial_angle=0.0
move_step_delay=0.03
hold_sec=0.8
```

舵机频率固定为 50Hz，占空比映射固定为：

```text
0 度   -> 5.0%
360 度 -> 10.0%
duty = 5.0 + angle / 360.0 * 5.0
```

## 药物绑定配置

默认配置文件：

```text
src/medicine_box/config/medicines.yaml
```

示例：

```yaml
medicines:
  aspirin:
    display_name: "阿司匹林"
    aliases: ["阿司匹林", "aspirin"]
    slot: 0
  amlodipine:
    display_name: "氨氯地平"
    aliases: ["氨氯地平", "降压药", "amlodipine"]
    slot: 2
```

字段含义：

```text
aspirin       程序内部使用的药物 key
display_name  对外显示的中文名称
aliases       ROSA 或服务调用时可识别的别名
slot          药格编号，最终角度 = slot * 90 度
```

修改配置后需要重新 build 并 source：

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select medicine_box
source install/setup.bash
```

## 启动节点

开发机 dry-run 模式，不会真实输出 PWM，适合先测试服务接口：

```bash
ros2 launch medicine_box medicine_box.launch.py dry_run:=true
```

RDK X5 实机模式：

```bash
ros2 launch medicine_box medicine_box.launch.py pwm_pin:=33
```

如果实际接线不是 33 号 board pin，改成对应引脚：

```bash
ros2 launch medicine_box medicine_box.launch.py pwm_pin:=<你的引脚号>
```

## 服务接口

服务名：

```text
/medicine_box/dispense
```

服务类型：

```text
task_manager_interfaces/srv/DispenseMedicine
```

请求字段：

```text
medicine_name  药物名称或别名
```

返回字段：

```text
success         是否成功
message         结果说明
canonical_name  匹配到的药物 key
angle           本次转到的角度
```

命令行测试：

```bash
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '阿司匹林'}"
```

也可以用别名：

```bash
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '降压药'}"
```

## ROSA 语音调用

ROSA 已新增 `dispense_medicine` 工具，并支持中文直连路由。

可以说：

```text
小智，给我拿阿司匹林
小智，我要吃降压药
小智，帮我取二甲双胍
```

ROSA 会调用：

```text
/medicine_box/dispense
```

然后 `medicine_box_node` 根据 `medicines.yaml` 找到药格并转动舵机。

## 实机校准建议

第一次实机测试建议按下面顺序：

```bash
colcon build --packages-select task_manager_interfaces medicine_box rosa_agent
source install/setup.bash
ros2 launch medicine_box medicine_box.launch.py dry_run:=true
```

确认服务能正常返回后，再启动真实 PWM：

```bash
ros2 launch medicine_box medicine_box.launch.py pwm_pin:=33
```

逐个测试药格：

```bash
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '阿司匹林'}"
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '二甲双胍'}"
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '降压药'}"
ros2 service call /medicine_box/dispense task_manager_interfaces/srv/DispenseMedicine "{medicine_name: '维生素D'}"
```

如果方向反了，可以先调整药物的 `slot` 绑定；如果舵机移动太快或太慢，再调整：

```text
move_step_delay
```

## 常见问题

如果日志提示找不到 `Hobot.GPIO`：

```text
说明当前不是 RDK X5 环境，或 Python 环境没有该库。
节点会自动退回 dry-run，不会真实控制舵机。
```

如果服务返回“未找到药物绑定”：

```text
检查 medicine_name 是否在 medicines.yaml 的 display_name 或 aliases 里。
```

如果舵机不动：

```text
1. 检查 PWM 组是否启用
2. 检查 pwm_pin 是否和接线一致
3. 检查舵机供电和共地
4. 检查是否误用了 dry_run:=true
```

如果日志提示 `This channel is in use`：

```text
说明当前 pwm_pin 对应的 PWM 通道已经被占用，常见原因是：

1. 代码在 GPIO.PWM(...) 前错误调用了 GPIO.setup(pin, GPIO.OUT)
2. 已经有一个 medicine_box_node 或其它 PWM 测试程序在运行
3. 上一次 PWM 程序异常退出，Hobot.GPIO 没有及时释放通道
4. 该引脚对应的 PWM 功能被其它进程占用
```

建议处理：

```bash
ros2 node list
ps -ef | grep medicine_box
ps -ef | grep python
```

如果确认有旧进程，先停止旧进程后再启动。必要时重启系统释放 PWM 状态：

```bash
sudo reboot
```

也可以先换一个已经启用 PWM 的 40pin 引脚测试：

```bash
ros2 launch medicine_box medicine_box.launch.py pwm_pin:=<其它PWM引脚>
```
