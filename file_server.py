#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# RK3568 开发板网页文件管理器：目录浏览 / 上传（含目录）/ 下载（文件与目录zip）/ 删除
# 依赖：仅 Python 3 标准库（http.server + cgi + zipfile）

import os
import re
import sys
import json
import html
import shutil
import tempfile
import zipfile
import datetime
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ===== 配置 =====
ROOT = "/userdata/www"          # 文件根目录（与 nginx 网页目录共用）
HOST = "0.0.0.0"
PORT = 80
MAX_NAME_LEN = 200              # 单个文件名长度上限

# ===== 页面模板 =====
PAGE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>文件管理器 - RK3568</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"Microsoft YaHei","PingFang SC",sans-serif;
         background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);
         min-height:100vh; padding:32px 16px; color:#e8eef1; }
  .wrap { max-width:920px; margin:0 auto; }
  h1 { font-size:24px; margin-bottom:4px; }
  .sub { color:#9fb3c8; font-size:13px; margin-bottom:20px; }
  .card { background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.12);
          border-radius:14px; padding:24px; margin-bottom:20px; }
  .card h2 { font-size:16px; margin-bottom:14px; color:#7fd1ae; }
  .drop { border:2px dashed rgba(255,255,255,0.3); border-radius:10px; padding:22px;
          text-align:center; color:#9fb3c8; cursor:pointer; transition:.2s; }
  .drop:hover, .drop.drag { border-color:#2ecc71; color:#2ecc71; background:rgba(46,204,113,0.06); }
  .drop input[type=file] { display:none; }
  #fileList { margin-top:12px; font-size:13px; color:#ffd479; text-align:left; word-break:break-all; }
  .btn { display:inline-block; background:#2ecc71; color:#0f2027; border:none; border-radius:8px;
         padding:10px 22px; font-size:14px; font-weight:700; cursor:pointer; margin-top:14px; }
  .btn:hover { background:#27ae60; }
  .btn:disabled { background:#777; cursor:not-allowed; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:10px 8px; border-bottom:1px solid rgba(255,255,255,0.08); }
  th { color:#9fb3c8; font-weight:600; font-size:13px; }
  td a { color:#7fd1ae; text-decoration:none; }
  td a:hover { text-decoration:underline; }
  .size { color:#9fb3c8; font-variant-numeric:tabular-nums; }
  .time { color:#9fb3c8; font-size:13px; }
  .empty { text-align:center; color:#9fb3c8; padding:18px 0; }
  .msg { padding:10px 14px; border-radius:8px; margin-bottom:16px; font-size:14px; }
  .msg.ok { background:rgba(46,204,113,0.15); color:#7fd1ae; border:1px solid rgba(46,204,113,0.4); }
  .msg.err { background:rgba(231,76,60,0.15); color:#ff7b6b; border:1px solid rgba(231,76,60,0.4); }
  .folder { color:#ffd479; }
  .del { color:#ff7b6b; margin-left:14px; }
  .del:hover { color:#ff5a4a; text-decoration:underline; }
  .zip { color:#7fd1ae; margin-left:14px; }
  .zip:hover { text-decoration:underline; }
  .crumb { margin-bottom:16px; font-size:14px; }
  .crumb a { color:#7fd1ae; text-decoration:none; margin-right:4px; }
  .crumb a:hover { text-decoration:underline; }
  .crumb .cur { color:#e8eef1; }
  code { background:rgba(0,0,0,0.35); padding:2px 6px; border-radius:6px; font-size:13px; color:#ffd479; }
  .prog-wrap { display:none; margin-bottom:16px; }
  .prog-wrap.on { display:block; }
  .progress { height:8px; background:rgba(255,255,255,0.12); border-radius:4px; overflow:hidden; }
  .progress .bar { height:100%; width:0%; background:linear-gradient(90deg,#2ecc71,#27ae60);
                   transition:width .15s; }
  .progress-label { margin-top:6px; font-size:12px; color:#9fb3c8; }
</style>
</head>
<body>
<div class="wrap">
  <h1>&#128193; 文件管理器</h1>
  <p class="sub">RK3568 开发板 · 根目录 <code>{ROOT}</code> · 支持目录上传 / 目录打包下载</p>
  <div class="prog-wrap" id="progWrap">
    <div class="progress"><div class="bar" id="progBar"></div></div>
    <div class="progress-label" id="progLabel"></div>
  </div>
"""

PAGE_TAIL = """
</div>
<script>
  var CURRENT_DIR = {CURRENT_DIR};
  var fileInput = document.getElementById('fileInput');
  var dirInput = document.getElementById('dirInput');
  var list = document.getElementById('fileList');
  var drop = document.getElementById('drop');
  var pendingFiles = [];   // 待上传列表：{file, path}
  var progWrap = document.getElementById('progWrap');
  var progBar = document.getElementById('progBar');
  var progLabel = document.getElementById('progLabel');

  function showProgress(pct, label){
    progWrap.className = 'prog-wrap on';
    progBar.style.width = pct + '%';
    progLabel.textContent = label;
  }
  function hideProgress(){ progWrap.className = 'prog-wrap'; }
  function fmtBytes(n){
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  // 实时速度：每 1 秒采样一次（瞬时窗口速度）；传输不足 1 秒时用平均速度兜底
  var _spd = 0, _spdB = 0, _spdT = 0, _spdTimer = null;
  function resetSpeed(){
    _spd = 0; _spdB = 0; _spdT = 0;
    if (_spdTimer) { clearInterval(_spdTimer); _spdTimer = null; }
  }
  function startSpeed(getBytes, render){
    resetSpeed();
    _spdT = Date.now(); _spdB = getBytes();
    _spdTimer = setInterval(function(){
      var t = Date.now(), b = getBytes();
      var dt = (t - _spdT) / 1000;
      if (dt > 0.05) _spd = (b - _spdB) / dt;
      _spdB = b; _spdT = t;
      render();
    }, 1000);
    render();
  }
  function stopSpeed(){
    if (_spdTimer) { clearInterval(_spdTimer); _spdTimer = null; }
  }
  function finalizeSpeed(finalBytes){
    // 总时长不足 1 秒：用 总字节/总耗时 作为平均速度补上
    if (_spd <= 0 && _spdT) {
      var el = (Date.now() - _spdT) / 1000;
      if (el > 0) _spd = finalBytes / el;
    }
  }
  function speedText(){ return _spd > 0 ? fmtBytes(_spd) + '/s' : ''; }

  drop.addEventListener('click', function(e) {
    if (e.target === fileInput || e.target === dirInput) return;
    fileInput.click();
  });
  drop.addEventListener('dragover', function(e){ e.preventDefault(); drop.classList.add('drag'); });
  drop.addEventListener('dragleave', function(){ drop.classList.remove('drag'); });

  function setPending(arr){ pendingFiles = arr; showPending(); }

  function showPending(){
    list.innerHTML = '';
    for (var i = 0; i < pendingFiles.length; i++) {
      var div = document.createElement('div');
      div.textContent = (i+1) + '. ' + pendingFiles[i].path;
      list.appendChild(div);
    }
  }

  fileInput.addEventListener('change', function(){
    var arr = [];
    for (var i = 0; i < fileInput.files.length; i++) arr.push({file:fileInput.files[i], path:fileInput.files[i].name});
    setPending(arr);
  });
  dirInput.addEventListener('change', function(){
    var arr = [];
    for (var i = 0; i < dirInput.files.length; i++) arr.push({file:dirInput.files[i], path:dirInput.files[i].webkitRelativePath || dirInput.files[i].name});
    setPending(arr);
  });

  // 递归读取拖拽目录的内部文件（webkitGetAsEntry，Chrome/Edge 支持）
  function collectEntry(entry, base, out, cb){
    if (entry.isFile) {
      entry.file(function(f){
        out.push({file:f, path: base ? base + '/' + f.name : f.name});
        cb();
      }, cb);
    } else if (entry.isDirectory) {
      var reader = entry.createReader();
      var batch = [];
      (function readBatch(){
        reader.readEntries(function(entries){
          if (!entries.length) {
            var n = batch.length, done = 0;
            if (!n) { cb(); return; }
            batch.forEach(function(en){
              collectEntry(en, base ? base + '/' + entry.name : entry.name, out, function(){ if (++done === n) cb(); });
            });
          } else {
            batch = batch.concat(entries);
            readBatch();
          }
        }, cb);
      })();
    } else cb();
  }

  drop.addEventListener('drop', function(e){
    e.preventDefault(); drop.classList.remove('drag');
    var items = e.dataTransfer.items || [];
    var entries = [], i;
    for (i = 0; i < items.length; i++) {
      if (items[i].kind === 'file') {
        var en = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
        if (en) entries.push(en);
      }
    }
    if (entries.length) {
      var out = [], n = entries.length, done = 0;
      entries.forEach(function(en){
        collectEntry(en, '', out, function(){ if (++done === n) setPending(out); });
      });
    } else {
      var arr = [];
      for (i = 0; i < e.dataTransfer.files.length; i++) arr.push({file:e.dataTransfer.files[i], path:e.dataTransfer.files[i].name});
      setPending(arr);
    }
  });

  function doUpload(){
    if (!pendingFiles.length) { alert('请先选择文件或文件夹'); return; }
    var fd = new FormData();
    pendingFiles.forEach(function(item){ fd.append('files', item.file, item.path); });
    var btn = document.getElementById('uploadBtn');
    btn.disabled = true; btn.textContent = '上传中...';
    var upLoaded = 0, upTotal = 0;
    function renderUp(){
      if (!upTotal) { showProgress(0, '正在上传 ... 0%（' + fmtBytes(upLoaded) + '，' + speedText() + '）'); return; }
      var pct = Math.round(upLoaded / upTotal * 100);
      showProgress(pct, '正在上传 ... ' + pct + '% （' + fmtBytes(upLoaded) + ' / ' + fmtBytes(upTotal) + '，' + speedText() + '）');
    }
    startSpeed(function(){ return upLoaded; }, renderUp);
    showProgress(0, '正在上传 ' + pendingFiles.length + ' 个文件 ...');
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/upload' + (CURRENT_DIR ? '?dir=' + encodeURIComponent(CURRENT_DIR) : ''), true);
    xhr.upload.onprogress = function(e){
      if (e.lengthComputable) { upLoaded = e.loaded; upTotal = e.total; }
    };
    xhr.onload = function(){
      if (xhr.status === 303 || xhr.status === 200) {
        progBar.style.width = '100%';
        progLabel.textContent = '&#10003; 上传完成，正在刷新列表 ...';
        setTimeout(function(){ location.href = '/'; }, 800);
      }
      else { stopSpeed(); hideProgress(); alert('上传失败（HTTP ' + xhr.status + '），请重试'); btn.disabled=false; btn.textContent='&#8593; 开始上传'; }
    };
    xhr.onerror = function(){ stopSpeed(); hideProgress(); alert('上传失败，请检查网络后重试'); btn.disabled=false; btn.textContent='&#8593; 开始上传'; };
    xhr.send(fd);
  }

  // 下载（文件/目录zip）：fetch 流式读取显示进度，完成后触发浏览器保存
  document.addEventListener('click', function(e) {
    var el = e.target;
    while (el && !(el.classList && el.classList.contains('dl'))) el = el.parentNode;
    if (!el) return;
    e.preventDefault();
    var href = el.getAttribute('href');
    var fname = el.getAttribute('data-file');
    var type = el.getAttribute('data-type') || 'file';
    var filename = fname || 'download';
    showProgress(0, '正在下载 ' + filename + ' ...');
    fetch(href).then(function(resp){
      if (!resp.ok) { hideProgress(); alert('下载失败（HTTP ' + resp.status + '）'); return null; }
      var total = +resp.headers.get('Content-Length') || 0;
      var received = 0;
      var chunks = [];
      var reader = resp.body.getReader();
      function renderDl(){
        if (total) {
          var pct = Math.round(received / total * 100);
          showProgress(pct, '正在下载 ' + filename + ' ... ' + pct + '% （' + fmtBytes(received) + ' / ' + fmtBytes(total) + '，' + speedText() + '）');
        } else {
          showProgress(0, '正在下载 ' + filename + ' ... ' + fmtBytes(received) + '，' + speedText());
        }
      }
      startSpeed(function(){ return received; }, renderDl);
      function pump(){
        return reader.read().then(function(r){
          if (r.done) {
            finalizeSpeed(received);
            renderDl();
            var blob = new Blob(chunks);
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
            stopSpeed();
            hideProgress();
            return;
          }
          chunks.push(r.value);
          received += r.value.length;
          return pump();
        });
      }
      return pump();
    }).catch(function(){
      stopSpeed();
      hideProgress();
      alert('下载失败，请检查网络后重试');
    });
  });

  // 删除（文件或目录）：事件委托，确认后 POST，成功后回当前目录
  document.addEventListener('click', function(e) {
    var el = e.target;
    while (el && !(el.classList && el.classList.contains('del'))) el = el.parentNode;
    if (!el) return;
    var name = el.getAttribute('data-name');
    var type = el.getAttribute('data-type');
    var dir = el.getAttribute('data-dir');
    var full = dir ? dir + '/' + name : name;
    if (type === 'dir') {
      if (!confirm('确定要删除整个目录 "' + full + '" 及其中的所有内容吗？此操作不可恢复！')) return;
    } else {
      if (!confirm('确定要删除文件 "' + full + '" 吗？此操作不可恢复。')) return;
    }
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/delete?file=' + encodeURIComponent(full) + '&type=' + type, true);
    xhr.onload = function() {
      if (xhr.status === 200) { location.href = '/'; }
      else { alert('删除失败（HTTP ' + xhr.status + '），请重试'); }
    };
    xhr.onerror = function(){ alert('删除失败，请检查网络后重试'); };
    xhr.send();
  });
</script>
</body>
</html>
"""


def fmt_size(n):
    # 人性化文件大小显示
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d B" % n


class Handler(BaseHTTPRequestHandler):
    server_version = "RK3568FileServer/2.0"

    # ---------- 工具方法 ----------
    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _safe_rel(self, raw):
        # 规范化相对路径（允许 / 分隔），逐段校验，拒绝绝对路径/穿越/特殊字符
        if not raw:
            return ""
        raw = raw.replace("\\", "/")
        if raw.startswith("/") or len(raw) > 1024:
            return None
        parts = raw.split("/")
        for p in parts:
            if not p or p in (".", "..") or re.search(r"[:]|[\x00-\x1f]", p):
                return None
        return raw

    def _join(self, rel):
        # 拼接并确保落在 ROOT 内
        base = os.path.realpath(ROOT)
        p = os.path.realpath(os.path.join(base, rel)) if rel else base
        if p != base and not p.startswith(base + os.sep):
            return None
        return p

    def _list_entries(self, cur):
        # 枚举当前目录条目（目录排前、按名称排序）
        base = self._join(cur)
        if base is None:
            return None, "路径无效"
        if not os.path.isdir(base):
            return None, "目录不存在"
        entries = []
        try:
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if os.path.isdir(full):
                    entries.append((name, True, 0, 0))
                else:
                    try:
                        st = os.stat(full)
                        entries.append((name, False, st.st_size, int(st.st_mtime)))
                    except OSError:
                        entries.append((name, False, 0, 0))
        except OSError as e:
            return None, str(e)
        entries.sort(key=lambda x: (not x[1], x[0].lower()))
        return entries, None

    def _crumbs(self, cur):
        # 面包屑：根 -> 逐级目录
        parts = [("根目录", "")]
        seg = ""
        for p in cur.split("/"):
            if not p:
                continue
            seg = p if not seg else seg + "/" + p
            parts.append((p, seg))
        return parts

    # ---------- 页面 ----------
    def _render_list(self, cur="", msg=None, err=None):
        entries, err2 = self._list_entries(cur)
        if err2:
            err = err2
            entries = []
        parts = [PAGE_HEAD.replace("{ROOT}", html.escape(ROOT))]
        if msg:
            parts.append('<div class="msg ok">&#10003; %s</div>' % html.escape(msg))
        if err:
            parts.append('<div class="msg err">&#9888; %s</div>' % html.escape(err))

        # 面包屑
        crumb_parts = ['<div class="crumb">']
        for label, seg in self._crumbs(cur):
            if seg == cur:
                crumb_parts.append('<span class="cur">&#128193; %s</span>' % html.escape(label))
            else:
                q = urllib.parse.quote(seg)
                crumb_parts.append('<a href="/?dir=%s">%s</a> &rsaquo; ' % (q, html.escape(label)))
        crumb_parts.append("</div>")
        parts.append("".join(crumb_parts))

        parts.append("""
  <div class="card">
    <h2>&#11021; 上传（支持整个文件夹）</h2>
    <div class="drop" id="drop">
      <div>&#128196; 点击选择<b>文件</b>或<b>文件夹</b>，或将文件拖拽到此处</div>
      <input type="file" name="files" id="fileInput" multiple>
      <input type="file" name="files" id="dirInput" webkitdirectory multiple>
      <div id="fileList"></div>
    </div>
    <button type="button" class="btn" id="uploadBtn" onclick="doUpload()">&#8593; 开始上传</button>
  </div>
  <div class="card">
    <h2>&#128193; 当前目录（%d 项）</h2>
    <table>
      <tr><th>名称</th><th>大小</th><th>修改时间</th><th>操作</th></tr>
""" % len(entries))
        if not entries:
            parts.append('<tr><td colspan="4" class="empty">目录为空</td></tr>')
        for name, is_dir, size, mtime in entries:
            name_html = html.escape(name)
            url = urllib.parse.quote(name)
            data_name = html.escape(name, quote=True)
            data_dir = html.escape(cur, quote=True)
            if is_dir:
                # 目录：可进入 + 打包下载
                subdir = (cur + "/" + name) if cur else name
                sub_q = urllib.parse.quote(subdir)
                parts.append(
                    '<tr><td class="folder">&#128193; <a href="/?dir=%s">%s</a></td>'
                    '<td class="size">-</td><td class="time">-</td>'
                    '<td><a class="zip dl" href="/download?file=%s&amp;type=dir" data-file="%s.zip">&#128230; 打包下载</a>'
                    '<a class="del" href="javascript:void(0)" data-name="%s" data-dir="%s" data-type="dir">&#128465; 删除</a></td></tr>'
                    % (sub_q, name_html, urllib.parse.quote(subdir), name_html, data_name, data_dir))
            else:
                t = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "-"
                rel = (cur + "/" + name) if cur else name
                rel_q = urllib.parse.quote(rel)
                parts.append(
                    '<tr><td>%s</td><td class="size">%s</td><td class="time">%s</td>'
                    '<td><a class="dl" href="/download?file=%s" data-file="%s">&#8595; 下载</a>'
                    '<a class="del" href="javascript:void(0)" data-name="%s" data-dir="%s" data-type="file">&#128465; 删除</a></td></tr>'
                    % (name_html, fmt_size(size), t, rel_q, data_name, data_name, data_dir))
        parts.append("</table></div>")
        parts.append(PAGE_TAIL.replace("{CURRENT_DIR}", json.dumps(cur)))
        self._send(200, "".join(parts))

    # ---------- 上传 ----------
    def _upload(self, cur=""):
        import cgi  # 仅上传时加载（Python 3.8 保留该模块）
        cur = self._safe_rel(cur)
        if cur is None:
            self._send(400, "Bad Request")
            return
        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self._send(400, "Bad Request: not multipart")
            return
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype},
            )
        except Exception as e:
            self._render_list(cur=cur, err="解析上传数据失败: %s" % e)
            return
        saved = []
        errors = []
        items = form["files"] if "files" in form else None
        if items is None:
            self._render_list(cur=cur, err="没有收到文件，请选择文件或文件夹后重试")
            return
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if not item.filename:
                continue
            # 文件名可能带相对路径（目录上传：dir/sub/a.txt）
            raw = item.filename.replace("\\", "/")
            if not raw or raw.startswith("/") or len(raw) > 2048:
                errors.append("文件名无效: %s" % html.escape(raw[:60]))
                continue
            parts = raw.split("/")
            clean = []
            ok = True
            for p in parts:
                if not p or p in (".", "..") or re.search(r"[:]|[\x00-\x1f]", p) or len(p) > MAX_NAME_LEN:
                    ok = False
                    break
                clean.append(p)
            if not ok:
                errors.append("%s: 文件名含非法路径" % html.escape(raw[:60]))
                continue
            rel = "/".join(clean)
            dest_rel = (cur + "/" + rel) if cur else rel
            dest = self._join(dest_rel)
            if dest is None:
                errors.append("%s: 路径越界" % html.escape(raw[:60]))
                continue
            try:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as out:
                    if hasattr(item.file, "read"):
                        shutil.copyfileobj(item.file, out, 1024 * 1024)
                    else:
                        out.write(item.value if isinstance(item.value, bytes) else str(item.value).encode("utf-8"))
                os.chmod(dest, 0o644)
                saved.append(rel)
            except OSError as e:
                errors.append("%s: %s" % (html.escape(rel), e))
        if saved:
            # PRG：上传成功则 303 跳回首页，避免停留在 /upload
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._render_list(cur=cur, err=(errors[0] if errors else "没有收到文件，请选择文件后重试"))

    # ---------- 下载 ----------
    def _download(self, rel, is_dir=False):
        rel = self._safe_rel(rel)
        if rel is None:
            self._send(400, "Bad Request")
            return
        full = self._join(rel)
        if full is None:
            self._send(403, "Forbidden")
            return
        if is_dir:
            self._download_dir(rel, full)
        else:
            self._download_file(rel, full)

    def _download_file(self, rel, full):
        if not os.path.isfile(full):
            self._send(404, "Not Found")
            return
        name = os.path.basename(full)
        disp = "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
            name.encode("ascii", "replace").decode(), urllib.parse.quote(name))
        try:
            size = os.path.getsize(full)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(full, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
        except (OSError, ConnectionError, BrokenPipeError):
            pass

    def _download_dir(self, rel, full):
        # 目录打包为 zip 流式返回
        if not os.path.isdir(full):
            self._send(404, "Not Found")
            return
        name = os.path.basename(full.rstrip("/")) or "dir"
        disp = "attachment; filename=\"%s.zip\"; filename*=UTF-8''%s.zip" % (
            name.encode("ascii", "replace").decode(), urllib.parse.quote(name))
        # 用临时文件打包，避免大目录占用内存
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.close()
        try:
            with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(full):
                    dirs.sort()
                    files.sort()
                    for fname in files:
                        fp = os.path.join(root, fname)
                        arc = os.path.relpath(fp, full)
                        zf.write(fp, arc)
            size = os.path.getsize(tmp.name)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", disp)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(tmp.name, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
        except (OSError, ConnectionError, BrokenPipeError):
            pass
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    # ---------- 删除 ----------
    def _delete(self, rel, is_dir=False):
        rel = self._safe_rel(rel)
        if rel is None:
            self._send(400, "Bad Request")
            return
        full = self._join(rel)
        if full is None:
            self._send(403, "Forbidden")
            return
        if is_dir:
            if not os.path.isdir(full):
                self._render_list(err="目录不存在: %s" % html.escape(rel))
                return
            try:
                shutil.rmtree(full)
                self._render_list(msg="已删除目录: %s" % html.escape(rel))
            except OSError as e:
                self._render_list(err="删除失败: %s" % e)
        else:
            if not os.path.isfile(full):
                self._render_list(err="文件不存在: %s" % html.escape(rel))
                return
            try:
                os.remove(full)
                self._render_list(msg="已删除: %s" % html.escape(rel))
            except OSError as e:
                self._render_list(err="删除失败: %s" % e)

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html", "/upload"):
            qs = urllib.parse.parse_qs(parsed.query)
            self._render_list(cur=qs.get("dir", [""])[0])
        elif parsed.path == "/download":
            qs = urllib.parse.parse_qs(parsed.query)
            rel = qs.get("file", [""])[0]
            is_dir = qs.get("type", [""])[0] == "dir"
            self._download(rel, is_dir)
        else:
            self._send(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/upload":
            qs = urllib.parse.parse_qs(parsed.query)
            self._upload(cur=qs.get("dir", [""])[0])
        elif parsed.path == "/delete":
            qs = urllib.parse.parse_qs(parsed.query)
            rel = qs.get("file", [""])[0]
            is_dir = qs.get("type", [""])[0] == "dir"
            self._delete(rel, is_dir)
        else:
            self._send(404, "Not Found")

    def log_message(self, fmt, *args):
        # 精简访问日志
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    if not os.path.isdir(ROOT):
        os.makedirs(ROOT, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print("File server started on http://%s:%d  (root: %s)" % (HOST, PORT, ROOT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
