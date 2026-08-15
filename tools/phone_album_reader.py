# -*- coding: utf-8 -*-
"""
手机相册读取工具（Windows + MTP 协议）
- 通过 Shell.Application COM 枚举已连接的 Android 手机
- 列出相册目录，按需下载图片到本地
依赖：comtypes
"""
import os
import sys
import time
import comtypes.client


class PhoneAlbumReader:
    def __init__(self):
        self.shell = comtypes.client.CreateObject("Shell.Application")

    def _get_items(self, folder_item):
        try:
            f = folder_item.GetFolder
            if f is None:
                return []
            items = f.Items()
            return [items.Item(i) for i in range(items.Count)]
        except Exception:
            return []

    def find_phone(self, keyword="iQOO"):
        """按关键字找手机设备，返回设备项"""
        for item in self.shell.Namespace(17).Items():
            if keyword.lower() in item.Name.lower():
                return item
        return None

    def enter(self, cur, parts):
        """按路径段进入目录"""
        for p in parts:
            cur = next((it for it in self._get_items(cur) if it.Name == p), None)
            if cur is None:
                return None
        return cur

    def list_albums(self, phone=None, internal="内部存储", root="DCIM"):
        """列出相册及图片数量"""
        if phone is None:
            return []
        inner = self.shell.Namespace(phone.Path).Items().Item(0)
        albums = []
        for it in self._get_items(inner):
            if not it.IsFolder:
                continue
            kids = self._get_items(it)
            imgs = [i for i in kids
                    if i.Name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic"))]
            if imgs:
                albums.append((it.Name, len(imgs)))
        return albums

    def download_album(self, phone, album_name, out_dir, limit=None):
        """下载指定相册的图片到本地"""
        os.makedirs(out_dir, exist_ok=True)
        dest = self.shell.NameSpace(out_dir)
        if dest is None:
            raise RuntimeError(f"无法打开本地目录: {out_dir}")
        inner = self.shell.Namespace(phone.Path).Items().Item(0)
        album = self.enter(inner, [album_name])
        if album is None:
            raise RuntimeError(f"找不到相册: {album_name}")
        imgs = [i for i in self._get_items(album)
                if i.Name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic"))]
        if limit:
            imgs = imgs[:limit]
        for it in imgs:
            dest.CopyHere(it, 0x14)  # 0x14 = 静默 + 不确认
            time.sleep(0.5)
        time.sleep(3)
        return [f for f in os.listdir(out_dir)]


if __name__ == "__main__":
    reader = PhoneAlbumReader()
    phone = reader.find_phone()
    if phone is None:
        print("未检测到手机，请先连接并开启文件传输模式")
        sys.exit(1)
    print(f"检测到手机: {phone.Name}")
    for name, count in reader.list_albums(phone):
        print(f"  相册: {name} | 图片: {count}")
