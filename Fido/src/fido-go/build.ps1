# 重新编译 FIDO2 虚拟设备端程序（Fido/fido-go.exe）
#
# 说明
# ----
# 这个 Go 程序只做「运输层」：USB/IP 设备模拟 + CTAPHID 分帧 + PIN 弹窗，
# 把 CTAP2 报文经命名管道转给 Python 后端（Module/FidoIpc.py）。
#
# 依赖的 virtual-fido 已经内联在 _vendor/virtual-fido（相对路径 replace），
# 因此**不需要联网、也不需要外部仓库**就能构建。相对上游做了三处补丁
# （都带 [TPMSC 补丁] 注释）：
#   1. usbip_server.go：并发处理 USB/IP 连接、detach 后优雅退出、写失败不崩；
#   2. usbip_server.go：只监听 127.0.0.1（避免防火墙弹窗/暴露到局域网）；
#   3. usbip.go：OP_REP_DEVLIST 手工序列化（上游 util.ToBE 对含切片的应答
#      返回空字节，usbip 客户端永远拿不到设备列表）。
#
# 用法: pwsh -File Fido\src\fido-go\build.ps1
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
        throw '未找到 go，请先安装 Go 1.22+（仅编译时需要，运行时不需要）'
    }
    $env:GOFLAGS = '-mod=mod'
    $output = Join-Path (Resolve-Path '..\..') 'fido-go.exe'
    Write-Host "[fido-go] 正在编译 -> $output"
    go build -trimpath -ldflags '-s -w' -o $output .
    if ($LASTEXITCODE -ne 0) { throw "go build 失败（退出码 $LASTEXITCODE）" }
    $info = Get-Item $output
    Write-Host ("[fido-go] 完成：{0}（{1:N0} 字节）" -f $info.Name, $info.Length)
}
finally {
    Pop-Location
}
