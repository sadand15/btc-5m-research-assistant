# 公开 Binance Dashboard

本次仅发布 `77db2659773d40b0f3b4af0d9b84c454ee3b9ea4` 的 Binance 实时研究页面。
VPS 使用独立目录 `~/btc5-public-dashboard/`，独立虚拟环境、只读模型副本和两个用户级 systemd 服务。
未改变原 `~/btc-5m-research-assistant` 源码、依赖、数据库、Docker 或 prospective 服务。

公开链路：手机/平板/电脑 → Cloudflare HTTPS Quick Tunnel → VPS 的 localhost:8767。
隧道只转发这个 HTTP 应用；HTTP Host 重写为 localhost，原应用的 host 检查保持启用。
不开放模型文件、目录列表、SSH、SQLite 或原始观察记录；只暴露应用已有只读路由。
没有登录限制，任何知道链接的人都可访问。

已配置用户级后台常驻及独立服务自动恢复。环境中的数值库以 VPS 的实际安装版本为准。
Cloudflared 使用官方 2026.10.0 linux-amd64，SHA256：
`d33ff2d14475178d2012c2c56beba87389ac5ded27649519f198a7d3134a99db`。
模型只接受原冻结 SHA256；不上传到 GitHub，不修改原件。

查看新网站服务（不操作原 collector）：

```sh
systemctl --user status btc5-public-dashboard.service btc5-public-tunnel.service
journalctl --user -u btc5-public-tunnel.service --no-pager
```

当前公开链接从 tunnel 日志取得。Quick Tunnel 是试用链接，没有固定域名或可用性保证；隧道重建后地址会改变。
服务器和网站后台保持运行时，不需要 Windows 电脑在线。
正式长期分享应配置自己的域名和具名 tunnel，或者其他有固定域名的主机入口。
参考：[Cloudflare 官方 Quick Tunnel 说明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

页面现有响应式布局覆盖手机、平板竖屏/横屏与桌面。预测仍是研究模型输出，不是保证胜率或真实交易服务。

## 发布验收（2026-10-12）

本次试用地址：<https://are-released-worm-pen.trycloudflare.com>。隧道重建后可能变化。
公网首页和 `/api/state` 均返回 200；模型、`.env` 和旧 manifest 路径返回 404。
使用公网链接在 iPhone 390×844、iPad 768×1024、横屏 1024×768 视口验收均通过，无横向溢出和 JavaScript 错误；这是浏览器视口检查，不等同所有实体设备实测。
两个新用户服务均 active/enabled，Linger=yes；无需 Windows 在线。
旧 VPS checkout 仍为 `265d6dd7f5f53baa98a8dbb3e45331e1245891bf` 且工作区干净。
依赖最终通过复制服务器现有 site-packages 到独立 venv 完成，排除旧项目 editable 入口，未修改原依赖。
