# Roban BLE GATT compatibility test (development only, insecure)

This root-level tool is not packaged or enabled by any production recipe. Its local name and UUID namespace intentionally differ from the production Secure Protocol v2 service, and it must never run on a production device.

- Advertisement name: `Roban-Bluetooth`
- Advertised service UUID: `a0a0ff10-0000-1000-8000-00805f9b34fb`
- Echo service: `7b7e0001-f3a0-4b6f-8a1e-4c70d2e2a001`
  - Echo characteristic: `7b7e0002-f3a0-4b6f-8a1e-4c70d2e2a001`
  - Properties: read, write, write without response, notify
- Compatibility service: `a0a0ff10-0000-1000-8000-00805f9b34fb`
  - Status `a0a0ff11-0000-1000-8000-00805f9b34fb`: read
  - Command `a0a0ff12-0000-1000-8000-00805f9b34fb`: write and write without response
  - Event `a0a0ff13-0000-1000-8000-00805f9b34fb`: notify

Subscribe to notifications, then write a short byte sequence to the echo
characteristic. The server stores the value and immediately sends the exact same
bytes as a notification. Reading the characteristic returns the last value.

Each test write must fit in one ATT value (`negotiated MTU - 3` bytes). Long and
reliable writes are intentionally not implemented in this minimal server.

The echo service initially contains ASCII `READY`. Reading the compatibility
status characteristic always returns ASCII `ok`. Writes to the compatibility
command characteristic are not processed; their complete hex and UTF-8 forms
are written to the system journal.

Neither service has an encryption, authentication, authorization, or pairing
requirement. The old Wi-Fi and Home Assistant provisioning tasks are not part of
this test server. Only the compatibility UUID is included in the advertisement;
the echo service is still visible during GATT discovery after connecting.

## 快速测试

1. 手机重新扫描并连接 `Roban-Bluetooth`。如果手机缓存了旧数据库，先忘记
   设备或执行一次 Refresh services。
2. 读取 `a0a0ff11-0000-1000-8000-00805f9b34fb`，结果应为 ASCII `ok`
   （HEX `6f 6b`）。
3. 订阅 `a0a0ff13-0000-1000-8000-00805f9b34fb` 的 Notify。当前测试服务
   只记录订阅状态，不会主动发送业务数据。
4. 向 `a0a0ff12-0000-1000-8000-00805f9b34fb` 写入任意短数据。Write
   Request 和 Write Without Response 均支持，数据只写入日志，不执行任务。
5. 如需测试双向回显，订阅 `7b7e0002-f3a0-4b6f-8a1e-4c70d2e2a001` 后向
   同一特征写入数据。

## 服务状态

```sh
systemctl status roban-gatt-test.service --no-pager
systemctl is-active bluetooth.service roban-gatt-test.service \
  saha-bt-wifi-provision.service
systemctl is-enabled roban-gatt-test.service \
  saha-bt-wifi-provision.service
```

正常结果：`bluetooth.service` 和 `roban-gatt-test.service` 为 `active`，原
`saha-bt-wifi-provision.service` 为 `inactive`、`masked`。

检查控制器、GATT UUID 和广告实例：

```sh
bluetoothctl show
btmgmt --index 0 info
btmgmt --index 0 advinfo
```

正常结果包括：

- Alias/本地名为 `Roban-Bluetooth`。
- UUID 列表包含 `a0a0ff10-...` 和 `7b7e0001-...`。
- `Pairable: no` 且 current settings 不含 `bondable`；测试特征无需配对。
- `Instances list with 1 item`，表示只有一个广告实例。

## 实时日志监控

应用日志：

```sh
journalctl -fu roban-gatt-test.service
```

最近 100 行：

```sh
journalctl -u roban-gatt-test.service -n 100 --no-pager
```

关键日志格式：

```text
legacy read: uuid=... value=b'ok'
legacy rx: uuid=... len=... type=... mtu=... device=... hex=... utf8='...'
legacy notifications enabled: uuid=...
rx: len=... type=... mtu=... device=... hex=...
tx echo notification: ... bytes
```

`legacy rx` 会打印完整接收内容，包括可能存在的密码或令牌，只能用于受控
调试环境。

BlueZ 当前以 debug 模式运行，详细的连接、ATT 和广告日志写在：

```sh
tail -f /var/log/messages
```

## 直接验证 D-Bus 对象

先找到 GATT 进程的 D-Bus unique name：

```sh
PID="$(systemctl show roban-gatt-test.service -p MainPID --value)"
BUS="$(busctl --system list --no-legend | \
  awk -v pid="$PID" '$2 == pid {print $1; exit}')"
echo "PID=$PID BUS=$BUS"
```

列出应用导出的全部对象。正常应有 6 个对象：2 个 Service、4 个
Characteristic。

```sh
busctl --system call "$BUS" \
  /org/roban/gatt_test \
  org.freedesktop.DBus.ObjectManager GetManagedObjects
```

读取广告内容：

```sh
busctl --system call "$BUS" \
  /org/roban/gatt_test/advertisement0 \
  org.freedesktop.DBus.Properties GetAll \
  s org.bluez.LEAdvertisement1
```

结果应包含 `Type=peripheral`、`LocalName=Roban-Bluetooth`，以及唯一广告
UUID `a0a0ff10-0000-1000-8000-00805f9b34fb`。

不使用手机直接读取 `ff11`：

```sh
busctl --system call "$BUS" \
  /org/roban/gatt_test/service1/char0 \
  org.bluez.GattCharacteristic1 ReadValue 'a{sv}' 0
```

预期结果为 `ay 2 111 107`，即 ASCII `ok`。

不使用手机向 `ff12` 写入 ASCII `test`，随后检查 journal：

```sh
busctl --system call "$BUS" \
  /org/roban/gatt_test/service1/char1 \
  org.bluez.GattCharacteristic1 WriteValue 'aya{sv}' \
  4 116 101 115 116 0
```

## HCI/ATT 抓包

实时查看控制器收发：

```sh
btmon --index 0
```

保存二进制抓包，结束时按 `Ctrl-C`：

```sh
btmon --index 0 --write /tmp/roban-ble.btsnoop
```

离线读取：

```sh
btmon --read /tmp/roban-ble.btsnoop
```

重点观察：LE Connection Complete、ATT Exchange MTU、Read By Group Type、
Read/Write Request、Handle Value Notification 和 Disconnect reason。

## 常见故障定位

### 扫描不到设备

```sh
systemctl is-active bluetooth.service roban-gatt-test.service
btmgmt --index 0 info
btmgmt --index 0 advinfo
journalctl -u roban-gatt-test.service -n 30 --no-pager
```

确认控制器为 `powered`、广告实例为 1，日志中同时出现 `GATT application
registered` 和 `advertisement registered`。

### 能连接但发现不了新特征

手机可能缓存了旧 GATT 数据库。忘记 `Roban-Bluetooth`、关闭再开启手机蓝牙，
然后重新扫描；支持该功能的调试工具可直接选择 Refresh services。

### 写入后没有业务响应

这是兼容测试服务的预期行为：`ff12` 只记录输入，不执行 Wi-Fi/HA 任务；
Write Without Response 在 ATT 层本来就没有写响应。请通过 `journalctl -fu`
确认 `legacy rx`。`ff13` 当前也只接受订阅，不主动发送数据。

### 连接约 4 秒后断开且没有 GATT 回调

检查内核 ATT/SMP 固定信道监听：

```sh
cat /sys/kernel/debug/bluetooth/l2cap
```

CID `0x0004` 是 ATT，CID `0x0006` 是 SMP。两者必须绑定相同的本地地址；
本机当前正常值均为公有地址 `6c:d5:52:cc:7e:7f (1)`。如果 ATT 使用公有地址、
SMP 却使用 `f2:54:53:42:ee:6d (2)`，手机 ATT 请求不会进入 BlueZ。

临时恢复步骤（下次开机前有效）：

```sh
systemctl stop --no-block roban-gatt-test.service
systemctl kill --kill-whom=all --signal=KILL roban-gatt-test.service
systemctl stop bluetooth.service
btmgmt --index 0 power off
btmgmt --index 0 static-addr 00:00:00:00:00:00
systemctl start bluetooth.service
systemctl start roban-gatt-test.service
cat /sys/kernel/debug/bluetooth/l2cap
```

默认镜像不再设置随机静态地址，控制器使用稳定的硬件公有地址，因此新镜像中
ATT 与 SMP 会保持相同的本地地址类型。
