# Git Worktree 并行开发工作流

本文档用于说明如何在同一个项目中使用 `git worktree` 同时推进多个优化方向，例如语音优化、跟随优化、视觉 BPU 优化和最终 demo 集成。

## 1. 为什么使用 git worktree

普通 Git 工作方式中，一个仓库目录一次只能 checkout 一个分支：

```text
/home/pan/Intelligent_robot
  当前只能处在 main 或某一个 feature 分支
```

当多个功能同时开发时，如果多个终端或多个 Codex 都在同一个目录里修改文件，很容易出现：

```text
改动互相覆盖
git status 混在一起
commit 边界不清
冲突难以定位
```

`git worktree` 可以让同一个 Git 仓库拥有多个独立工作目录，每个目录对应一个不同分支：

```text
/home/pan/Intelligent_robot              主工作区
/home/pan/Intelligent_robot_voice_opt    语音优化分支
/home/pan/Intelligent_robot_follow_opt   跟随优化分支
/home/pan/Intelligent_robot_vision_bpu   视觉 BPU 分支
```

这些目录共享同一个 Git 历史，但文件工作区互相独立，适合多个功能并行开发。

## 2. 推荐分支规划

针对当前养老陪护机器人项目，建议按功能拆分分支：

```text
feature/voice-opt
  语音优化：本地快速命令、TTS 缓存、唤醒流程优化

feature/follow-opt
  跟随优化：局部速度控制、/cmd_vel_follow、velocity_mux

feature/vision-bpu
  视觉优化：RDK X5 BPU、YOLO/YOLOPose、深度定位

feature/demo-manager
  demo 编排：最终演示流程、任务串联

integration/final-demo
  集成分支：合并多个 feature 分支后做统一验收
```

## 3. 创建多个 worktree

在主仓库目录中执行：

```bash
cd /home/pan/Intelligent_robot

git worktree add ../Intelligent_robot_voice_opt -b feature/voice-opt
git worktree add ../Intelligent_robot_follow_opt -b feature/follow-opt
git worktree add ../Intelligent_robot_vision_bpu -b feature/vision-bpu
git worktree add ../Intelligent_robot_demo_manager -b feature/demo-manager
```

创建后目录结构类似：

```text
/home/pan/Intelligent_robot
/home/pan/Intelligent_robot_voice_opt
/home/pan/Intelligent_robot_follow_opt
/home/pan/Intelligent_robot_vision_bpu
/home/pan/Intelligent_robot_demo_manager
```

查看当前所有 worktree：

```bash
git worktree list
```

## 4. 在不同 worktree 中开发

### 4.1 语音优化

```bash
cd /home/pan/Intelligent_robot_voice_opt
git status
```

在这个目录中只做语音相关修改，例如：

```text
src/rosa_agent/rosa_agent/always_listen_voice_cli.py
src/rosa_agent/rosa_agent/voice.py
src/rosa_agent/rosa_agent/config.py
src/rosa_agent/rosa_agent/action_tools.py
```

提交：

```bash
git add src/rosa_agent/
git commit -m "optimize voice interaction"
git push -u origin feature/voice-opt
```

### 4.2 跟随优化

```bash
cd /home/pan/Intelligent_robot_follow_opt
```

在这个目录中只做跟随控制相关修改，例如：

```text
src/follower_controller/
src/task_manager/launch/robot_server.launch.py
```

提交：

```bash
git add src/follower_controller/ src/task_manager/launch/robot_server.launch.py
git commit -m "add local cmd_vel follower"
git push -u origin feature/follow-opt
```

### 4.3 视觉 BPU 优化

```bash
cd /home/pan/Intelligent_robot_vision_bpu
```

在这个目录中只做视觉相关修改，例如：

```text
src/person_tracker/
src/vision_perception_bpu/
src/task_manager/launch/robot_server.launch.py
```

提交：

```bash
git add src/person_tracker/ src/vision_perception_bpu/ src/task_manager/launch/robot_server.launch.py
git commit -m "add bpu vision backend"
git push -u origin feature/vision-bpu
```

## 5. 每个 worktree 独立编译

每个 worktree 都是一个完整工作区，可以单独编译：

```bash
cd /home/pan/Intelligent_robot_voice_opt
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
```

另一个分支：

```bash
cd /home/pan/Intelligent_robot_follow_opt
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
```

注意：

```text
每个 worktree 有自己的 build/ install/ log/
互相不会覆盖
```

## 6. 收敛到集成分支

不要直接把所有功能一次性合进 `main`。推荐先创建集成分支：

```bash
cd /home/pan/Intelligent_robot
git checkout main
git pull
git checkout -b integration/final-demo
```

然后逐个合并功能分支。

推荐顺序：

```text
1. feature/voice-opt
2. feature/follow-opt
3. feature/vision-bpu
4. feature/demo-manager
```

执行：

```bash
git merge feature/voice-opt
colcon build

git merge feature/follow-opt
colcon build

git merge feature/vision-bpu
colcon build

git merge feature/demo-manager
colcon build
```

每合并一个分支后都要编译和做最小验收，不要等全部合完再测试。

## 7. 冲突处理

如果合并时出现冲突：

```bash
git status
```

打开冲突文件，找到：

```text
<<<<<<< HEAD
当前分支内容
=======
被合并分支内容
>>>>>>> feature/xxx
```

手动整理为最终需要的内容，然后：

```bash
git add 冲突文件
git commit
```

如果冲突太复杂，想放弃本次合并：

```bash
git merge --abort
```

## 8. 集成验收

集成分支上至少做以下检查：

```bash
colcon build
source install/setup.bash
ros2 launch task_manager robot_server.launch.py
```

建议逐项验收：

```text
普通导航：
  /robot_server/start_task task_type=navigate

叫醒任务：
  /robot_server/start_task task_type=wake_up

语音命令：
  小智，去厨房
  小智，跟着我
  小智，停下

跟随任务：
  /robot_mode == FOLLOWING 时才输出跟随控制

视觉任务：
  /person_position
  /person_distance
  /fall_detected

应急抢占：
  /fall_detected true 后进入 EMERGENCY
```

## 9. 合回 main

集成分支验收通过后，再合回 `main`：

```bash
cd /home/pan/Intelligent_robot
git checkout main
git pull
git merge integration/final-demo
colcon build
git push
```

如果走远程协作，也可以把 `integration/final-demo` 推上去：

```bash
git push -u origin integration/final-demo
```

然后通过 Pull Request 合并。

## 10. 删除不再需要的 worktree

当某个功能分支已经合并，并且不再需要单独目录时，可以删除 worktree。

先确认没有未提交改动：

```bash
cd /home/pan/Intelligent_robot_voice_opt
git status
```

如果工作区干净，回主仓库删除：

```bash
cd /home/pan/Intelligent_robot
git worktree remove ../Intelligent_robot_voice_opt
```

如果目录已经被手动删除，可以清理记录：

```bash
git worktree prune
```

注意：

```text
git worktree remove 只删除额外工作目录
不会删除 Git 分支
不会删除已经提交的历史
```

如果分支也不再需要：

```bash
git branch -d feature/voice-opt
```

删除远程分支：

```bash
git push origin --delete feature/voice-opt
```

## 11. 常用命令速查

创建 worktree：

```bash
git worktree add ../Intelligent_robot_voice_opt -b feature/voice-opt
```

查看 worktree：

```bash
git worktree list
```

进入某个 worktree：

```bash
cd ../Intelligent_robot_voice_opt
```

提交分支：

```bash
git add .
git commit -m "message"
git push -u origin feature/voice-opt
```

创建集成分支：

```bash
git checkout main
git pull
git checkout -b integration/final-demo
```

合并功能分支：

```bash
git merge feature/voice-opt
```

删除 worktree：

```bash
git worktree remove ../Intelligent_robot_voice_opt
```

清理坏掉的 worktree 记录：

```bash
git worktree prune
```

## 12. 推荐原则

```text
一个 worktree 只做一个方向。
一个分支只解决一类问题。
每个分支都要能单独 build。
每次合并后都要立即测试。
main 只接收已经集成验收通过的结果。
```

对于当前项目，推荐并行开发但集中验收：

```text
voice-opt     语音体验
follow-opt    跟随控制
vision-bpu    BPU 视觉
demo-manager  演示编排
integration   统一联调
main          稳定主线
```
