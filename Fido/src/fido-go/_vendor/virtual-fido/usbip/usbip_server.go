package usbip

import (
	"net"
	"strings"
	"sync"
	"syscall"

	"github.com/bulwarkid/virtual-fido/util"
)

var usbipLogger = util.NewLogger("[USBIP] ", util.LogLevelTrace)
var errLogger = util.NewLogger("[ERR] ", util.LogLevelEnabled)

type USBIPServer struct {
	devices []USBIPDevice
}

func NewUSBIPServer(devices []USBIPDevice) *USBIPServer {
	server := new(USBIPServer)
	server.devices = devices
	return server
}

func (server *USBIPServer) Start() {
	usbipLogger.Println("Starting USBIP server...")
	// [TPMSC 补丁] 只监听回环地址：USB/IP 设备端只服务本机的 usbip 客户端，
	// 既避免 Windows 防火墙弹窗，也避免把设备暴露到局域网。
	listener, err := net.Listen("tcp", "127.0.0.1:3240")
	util.CheckErr(err, "Could not create listener")
	for {
		connection, err := listener.Accept()
		if err != nil {
			usbipLogger.Printf("Connection accept error: %v", err)
			continue
		}
		if !strings.HasPrefix(connection.RemoteAddr().String(), "127.0.0.1") {
			usbipLogger.Printf("Connection attempted from non-local address: %s", connection.RemoteAddr().String())
			connection.Close()
			continue
		}
		usbipConn := newUSBIPConnection(server, connection)
		go util.Try(func() {
			usbipConn.handle()
		}, func(err interface{}) {
			errLogger.Printf("Connection error: %v", err)
			connection.Close()
		})
	}
}

func (server *USBIPServer) getDevice(busID string) USBIPDevice {
	var device USBIPDevice = nil
	for _, other := range server.devices {
		if other.BusID() == busID {
			device = other
			break
		}
	}
	return device
}

type usbipConnection struct {
	responseMutex *sync.Mutex
	conn          net.Conn
	server        *USBIPServer
}

func newUSBIPConnection(server *USBIPServer, conn net.Conn) *usbipConnection {
	usbipConn := new(usbipConnection)
	usbipConn.responseMutex = &sync.Mutex{}
	usbipConn.conn = conn
	usbipConn.server = server
	return usbipConn
}

func (conn *usbipConnection) handle() {
	for {
		header := util.ReadBE[usbipControlHeader](conn.conn)
		usbipLogger.Printf("[CONTROL MESSAGE] %#v\n\n", header)
		if header.Command == usbipCommandOpReqDevlist {
			reply := newOpRepDevlist(conn.server.devices)
			usbipLogger.Printf("[OP_REP_DEVLIST] %#v\n\n", reply)
			// [TPMSC 补丁] 用逐字段序列化，util.ToBE 对含切片的应答会返回空字节
			conn.writeResponse(marshalOpRepDevlist(reply))
		} else if header.Command == usbipCommandOpReqImport {
			busIDData := util.Read(conn.conn, 32)
			busID := util.CStringToString(busIDData)
			device := conn.server.getDevice(busID)
			if device == nil {
				// Device not found
				reply := opRepImportError(1)
				conn.writeResponse(util.ToBE(reply))
				continue
			}
			reply := newOpRepImport(device)
			usbipLogger.Printf("[OP_REP_IMPORT] %s\n\n", reply)
			conn.writeResponse(util.ToBE(reply))
			conn.handleCommands(device)
			// handleCommands 返回说明连接已断开，退出
			return
		} else {
			usbipLogger.Printf("Unknown Command Code: %d", header.Command)
		}
	}
}

func (conn *usbipConnection) handleCommands(device USBIPDevice) {
	for {
		done := false
		util.Try(func() {
			header := util.ReadBE[usbipMessageHeader](conn.conn)
			usbipLogger.Printf("[MESSAGE HEADER] %s\n\n", header)
			if header.Command == usbipCmdSubmit {
				conn.handleCommandSubmit(device, header)
			} else if header.Command == usbipCmdUnlink {
				conn.handleCommandUnlink(device, header)
			} else {
				usbipLogger.Printf("Unsupported Command: %#v\n\n", header)
			}
		}, func(err interface{}) {
			// 连接断开（detach/close）是正常现象，仅记录简短提示，不打印 panic 堆栈
			errLogger.Printf("Connection closed, stopping command loop")
			done = true
		})
		if done {
			conn.conn.Close()
			return
		}
	}
}

func (conn *usbipConnection) handleCommandSubmit(device USBIPDevice, header usbipMessageHeader) {
	command := util.ReadBE[usbipCommandSubmitBody](conn.conn)
	usbipLogger.Printf("[COMMAND SUBMIT] %s\n\n", command)
	transferBuffer := make([]byte, command.TransferBufferLength)
	if header.Direction == usbipDirOut && command.TransferBufferLength > 0 {
		_, err := conn.conn.Read(transferBuffer)
		util.CheckErr(err, "Could not read transfer buffer")
	}
	// Getting the reponse may not be immediate, so we need a callback
	onReturnSubmit := func(response []byte) {
		if response != nil {
			copy(transferBuffer, response)
		}
		replyHeader := header.replyHeader()
		replyBody := usbipReturnSubmitBody{
			Status:          0,
			ActualLength:    uint32(len(transferBuffer)),
			StartFrame:      0,
			NumberOfPackets: 0,
			ErrorCount:      0,
			Padding:         0,
		}
		usbipLogger.Printf("[RETURN SUBMIT] %v %#v\n\n", replyHeader, replyBody)
		reply := util.Concat(util.ToBE(replyHeader), util.ToBE(replyBody))
		if header.Direction == usbipDirIn {
			usbipLogger.Printf("[RETURN SUBMIT] DATA: %#v\n\n", transferBuffer)
			reply = append(reply, transferBuffer...)
		}
		conn.writeResponse(reply)
	}
	device.HandleMessage(header.SequenceNumber, onReturnSubmit, header.Endpoint, command.SetupBytes[:], transferBuffer)
}

func (conn *usbipConnection) handleCommandUnlink(device USBIPDevice, header usbipMessageHeader) {
	unlink := util.ReadBE[usbipCommandUnlinkBody](conn.conn)
	usbipLogger.Printf("[COMMAND UNLINK] %#v\n\n", unlink)
	var status int32
	if device.RemoveWaitingRequest(unlink.UnlinkSequenceNumber) {
		status = -int32(syscall.ECONNRESET)
	} else {
		status = -int32(syscall.ENOENT)
	}
	replyHeader := header.replyHeader()
	replyBody := usbipReturnUnlinkBody{
		Status:  status,
		Padding: [24]byte{},
	}
	reply := util.Concat(
		util.ToBE(replyHeader),
		util.ToBE(replyBody),
	)
	conn.writeResponse(reply)
}

func (conn *usbipConnection) writeResponse(data []byte) {
	conn.responseMutex.Lock()
	defer conn.responseMutex.Unlock()
	defer func() {
		if r := recover(); r != nil {
			// 连接已断开（detach 后），静默忽略写入错误
			errLogger.Printf("writeResponse: connection closed, ignoring write error")
		}
	}()
	usbipLogger.Printf("[WRITE] %d bytes", len(data))
	written, err := conn.conn.Write(data)
	if err != nil {
		errLogger.Printf("writeResponse: 写入失败（%d/%d）: %v", written, len(data), err)
	}
}
