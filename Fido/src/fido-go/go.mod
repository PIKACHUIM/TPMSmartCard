module github.com/pikachuim/tpmsc-fido

go 1.22

require (
	github.com/Microsoft/go-winio v0.6.2
	github.com/bulwarkid/virtual-fido v0.0.0-20230103163558-3d5b5e5b5b5b
)

require (
	github.com/fxamacker/cbor/v2 v2.4.0 // indirect
	github.com/x448/float16 v0.8.4 // indirect
	golang.org/x/sys v0.10.0 // indirect
)

// 内置一份打过补丁的 virtual-fido（并发处理 USB/IP 连接、detach 后优雅退出），
// 避免构建时依赖外部目录，也避免上游未修复的问题。
replace github.com/bulwarkid/virtual-fido => ./_vendor/virtual-fido
