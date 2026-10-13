# RK3568 文件服务器备份说明

备份日期：2026-10-12
开发板：RK3568（192.168.18.71，root / xxxx）

## 备份内容

| 文件 | 对应开发板位置 | 用途 |
|---|---|---|
| file_server.py | /userdata/app/file_server.py | 文件服务器核心程序（80 端口，上传/下载/删除/列表） |
| S99fileserver | /etc/init.d/S99fileserver | 开机自启脚本（需 755 权限） |
| nginx.conf | /etc/nginx/nginx.conf | nginx 配置：监听 8080，网页根目录 /userdata/www |
| index.html | /userdata/www/index.html | 网页首页（测试页） |

## 恢复步骤（在新板/重刷系统后）

1. 上传 4 个文件到对应位置：
   - `file_server.py` → `/userdata/app/file_server.py`
   - `S99fileserver` → `/etc/init.d/S99fileserver`
   - `nginx.conf` → `/etc/nginx/nginx.conf`
   - `index.html` → `/userdata/www/index.html`
2. 设置权限：
   ```
   chmod 755 /userdata/app/file_server.py /etc/init.d/S99fileserver
   chmod 644 /userdata/www/index.html
   ```
3. 启动服务：
   ```
   /etc/init.d/S99fileserver start   # 启动文件服务器（80 端口）
   /etc/init.d/S50nginx start        # 启动 nginx（8080 端口，如未运行）
   ```
   或直接重启开发板，两个服务会自动启动。

## 访问地址

- 文件管理器（上传/下载/删除）：http://192.168.18.71/
- nginx 静态网页：http://192.168.18.71:8080/
- SSH：ssh root@192.168.18.71（密码 xxxx）

## 注意

- 上传到 /userdata/www 的用户文件不在本备份内，如需备份请单独打包该目录
- 网页删除功能会直接删除文件且不可恢复，删除 index.html 会使首页 404（重新上传即可）
