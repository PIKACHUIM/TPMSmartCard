// Command tpmsc 是 TPMSmartCard 的跨平台命令行入口。
//
// 用途：
//   - 环境自检（doctor）：不打开界面就能确认平台能力、TPM/读卡器与工具链
//   - 建卡 / 删卡 / 改 PIN / 列证书
//   - 备份检查与云端取回
//   - 启动本地 API（serve），供 Wails 外壳或浏览器访问
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/PIKACHUIM/tpmsmartcard/internal/api"
	"github.com/PIKACHUIM/tpmsmartcard/internal/backup"
	"github.com/PIKACHUIM/tpmsmartcard/internal/cloud"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform"
	"github.com/PIKACHUIM/tpmsmartcard/internal/platform/factory"
	"github.com/PIKACHUIM/tpmsmartcard/internal/protocol"
	"github.com/PIKACHUIM/tpmsmartcard/ui"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	ctx := context.Background()
	switch os.Args[1] {
	case "doctor":
		runDoctor(ctx)
	case "card":
		runCard(ctx, os.Args[2:])
	case "cert":
		runCert(ctx, os.Args[2:])
	case "backup":
		runBackup(os.Args[2:])
	case "cloud":
		runCloud(ctx, os.Args[2:])
	case "serve":
		runServe(ctx, os.Args[2:])
	case "version", "-v", "--version":
		fmt.Println(protocol.Version)
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Println(`tpmsc —— TPM 虚拟智能卡命令行

用法:
  tpmsc doctor                        平台自检（能力矩阵 / TPM / 读卡器）
  tpmsc card list                     列出卡片
  tpmsc card create -name 名称 -pin PIN [-puk PUK]
  tpmsc card delete -id <卡片ID>
  tpmsc card pin -id <卡片ID> -new <新PIN>
  tpmsc cert list [-card <卡片ID>]
  tpmsc backup inspect -file <备份.tsb>
  tpmsc cloud fetch-code -url <https://...> -code <取件码> [-out payload.json]
  tpmsc cloud fetch-key  -url <https://...> [-out payload.json]
  tpmsc serve [-addr 127.0.0.1:1026]`)
}

func runDoctor(ctx context.Context) {
	slots := factory.Slots()
	results := make([]platform.SlotInfo, 0, len(slots))
	for _, slot := range slots {
		info, err := slot.Info(ctx)
		if err != nil {
			fmt.Fprintf(os.Stderr, "卡槽 %s 不可用: %v\n", slot.ID(), err)
			continue
		}
		results = append(results, info)
	}
	payload := map[string]any{
		"version": protocol.Version,
		"slots":   results,
	}
	printJSON(payload)
}

func runCard(ctx context.Context, args []string) {
	if len(args) == 0 {
		usage()
		os.Exit(2)
	}
	switch args[0] {
	case "list":
		cards := []platform.Card{}
		for _, slot := range factory.Slots() {
			items, err := slot.List(ctx)
			if err != nil {
				fmt.Fprintf(os.Stderr, "读取 %s 失败: %v\n", slot.ID(), err)
				continue
			}
			cards = append(cards, items...)
		}
		printJSON(cards)
	case "create":
		fs := flag.NewFlagSet("card create", flag.ExitOnError)
		name := fs.String("name", "", "卡片名称")
		pin := fs.String("pin", "", "PIN")
		puk := fs.String("puk", "", "PUK（Linux 作为 SO PIN）")
		_ = fs.Parse(args[1:])
		slot := pickSlot(ctx, "create")
		card, err := slot.Create(ctx, platform.CreateOptions{Name: *name, PIN: *pin, PUK: *puk})
		exitOnErr(err)
		printJSON(card)
	case "delete":
		fs := flag.NewFlagSet("card delete", flag.ExitOnError)
		id := fs.String("id", "", "卡片 ID")
		_ = fs.Parse(args[1:])
		slot := resolveSlot(ctx, *id)
		exitOnErr(slot.Delete(ctx, *id))
		fmt.Println("已删除", *id)
	case "pin":
		fs := flag.NewFlagSet("card pin", flag.ExitOnError)
		id := fs.String("id", "", "卡片 ID")
		newPIN := fs.String("new", "", "新 PIN")
		_ = fs.Parse(args[1:])
		slot := resolveSlot(ctx, *id)
		exitOnErr(slot.SetPIN(ctx, *id, "", *newPIN))
		fmt.Println("PIN 已更新")
	default:
		usage()
		os.Exit(2)
	}
}

func runCert(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("cert", flag.ExitOnError)
	cardID := fs.String("card", "", "卡片 ID（留空表示全部）")
	if len(args) > 0 && args[0] == "list" {
		_ = fs.Parse(args[1:])
	} else {
		_ = fs.Parse(args)
	}

	var certs []platform.Certificate
	if *cardID != "" {
		slot := resolveSlot(ctx, *cardID)
		items, err := slot.ListCertificates(ctx, *cardID)
		exitOnErr(err)
		certs = items
	} else {
		for _, slot := range factory.Slots() {
			cards, err := slot.List(ctx)
			if err != nil {
				continue
			}
			for _, card := range cards {
				if items, err := slot.ListCertificates(ctx, card.ID); err == nil {
					certs = append(certs, items...)
				}
			}
		}
	}
	if certs == nil {
		certs = []platform.Certificate{}
	}
	printJSON(certs)
}

func runBackup(args []string) {
	if len(args) == 0 || args[0] != "inspect" {
		usage()
		os.Exit(2)
	}
	fs := flag.NewFlagSet("backup inspect", flag.ExitOnError)
	file := fs.String("file", "", "备份文件路径")
	_ = fs.Parse(args[1:])
	manifest, err := backup.Inspect(*file)
	if err != nil {
		fmt.Fprintln(os.Stderr, "备份检查失败:", err)
		os.Exit(1)
	}
	printJSON(manifest)
}

func runCloud(ctx context.Context, args []string) {
	if len(args) == 0 {
		usage()
		os.Exit(2)
	}
	mode := args[0]
	fs := flag.NewFlagSet("cloud", flag.ExitOnError)
	baseURL := fs.String("url", "", "下发服务地址")
	code := fs.String("code", "", "取件码")
	out := fs.String("out", "", "输出文件（默认打印到标准输出）")
	_ = fs.Parse(args[1:])
	if *baseURL == "" {
		fmt.Fprintln(os.Stderr, "缺少 -url")
		os.Exit(2)
	}

	client := cloud.New(*baseURL)
	var delivered cloud.Delivered
	var err error
	switch mode {
	case "fetch-code":
		delivered, err = client.FetchByCode(ctx, *code)
	case "fetch-key":
		delivered, err = client.FetchByPublicKey(ctx, *baseURL)
	default:
		usage()
		os.Exit(2)
	}
	exitOnErr(err)

	if *out == "" {
		fmt.Println(string(delivered.Payload))
		return
	}
	exitOnErr(os.WriteFile(*out, delivered.Payload, 0o600))
	fmt.Println("已写入", *out)
}

func runServe(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("serve", flag.ExitOnError)
	addr := fs.String("addr", "127.0.0.1:1026", "监听地址")
	_ = fs.Parse(args)

	server := api.New(api.Options{
		Slots:      factory.Slots(),
		UIFS:       ui.FS(),
		Token:      os.Getenv("TPMSC_LOCAL_TOKEN"),
		BackupsDir: defaultBackupDir(),
		Platform:   "",
	})
	httpServer := &http.Server{
		Addr:              *addr,
		Handler:           server.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	go func() {
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			fmt.Fprintln(os.Stderr, "本地服务退出:", err)
		}
	}()
	fmt.Printf("本地 API: http://%s  (Ctrl+C 退出)\n", *addr)

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(shutdownCtx)
}

func pickSlot(ctx context.Context, action string) platform.Slot {
	for _, slot := range factory.Slots() {
		info, err := slot.Info(ctx)
		if err != nil {
			continue
		}
		if action == "create" && info.Capability.CreateCard {
			return slot
		}
	}
	fmt.Fprintln(os.Stderr, "当前平台没有可用的卡槽执行该操作")
	os.Exit(1)
	return nil
}

func resolveSlot(ctx context.Context, cardID string) platform.Slot {
	for _, slot := range factory.Slots() {
		cards, err := slot.List(ctx)
		if err != nil {
			continue
		}
		for _, card := range cards {
			if card.ID == cardID {
				return slot
			}
		}
	}
	fmt.Fprintf(os.Stderr, "找不到卡片 %s\n", cardID)
	os.Exit(1)
	return nil
}

func defaultBackupDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "backups"
	}
	return home + string(os.PathSeparator) + "TPMSmartCard" + string(os.PathSeparator) + "backups"
}

func printJSON(value any) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(value)
}

func exitOnErr(err error) {
	if err == nil {
		return
	}
	message := err.Error()
	if strings.Contains(message, platform.ErrUnsupported.Error()) {
		fmt.Fprintln(os.Stderr, "不支持:", strings.TrimPrefix(message, platform.ErrUnsupported.Error()+": "))
		os.Exit(3)
	}
	fmt.Fprintln(os.Stderr, "失败:", message)
	os.Exit(1)
}
