# AES 密钥怎么放

导出器要读游戏 pak，必须先有 AES 密钥文件（通常叫 `AESKey1.json`）。程序**不附带**密钥，
需要你自己准备一份。放的位置有两种，任选其一：

1. **设置里选**：打开「设置 → 密钥 JSON」右边的「选择…」，指到你的 `AESKey1.json`。
   这个路径会记在 `%LOCALAPPDATA%\AtlasMap\settings.json` 里。
2. **放程序目录**：把文件放到程序目录下的 `assets\AESKey1.json`，程序启动时会自动找到。
   单文件版（`AtlasMap-Standalone.exe`）也可以直接放在 exe 同级的 `AESKey1.json`。

程序每次开始导出都会按「设置里的路径 → 程序目录 → 程序目录\assets → 配置目录」的顺序找一遍，
设置里那条路径失效（比如换了电脑、文件被挪走）也不会直接报错，会自动改用找到的那份。

## 找不到会怎样

界面会直接提示「还没有 AES 密钥文件」并展开设置项，不会跑到一半才失败。

如果日志里出现下面这句，就是密钥没就位：

```
[dfmap] FATAL FileNotFoundException: AES key file not found: ...
```

按上面的两种放法处理后再导一次即可。密钥文件本身不要提交进仓库、也不要发给别人。
