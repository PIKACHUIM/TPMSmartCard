; =============================================================================
;  TPM 虚拟智能卡管理工具 —— Inno Setup 安装包脚本
;
;  本地编译：  iscc install.iss
;  CI 编译：   .github/workflows/build-client-release.yml（自动设置下列环境变量）
;
;  可选环境变量（都有默认值，本地直接编译也能用）：
;    TPMSMART_VERSION      显示版本号，如 1.6.0 / 1.6.2026.1012（默认 1.6.0）
;    TPMSMART_VERSION4     写入 exe 版本资源的 4 段版本号，如 1.6.0.0（默认 1.6.0.0）
;    TPMSMART_PACKAGENAME  产物基础名，如 TPMSmartCard-1.6-win64（默认 TPMSmartCard-win64）
;    TPMSMART_BUILDDIR     cx_Freeze 输出目录（默认 build\exe.win-amd64-3.11）
;
;  语言：简体中文 + 英文。中文语言包使用随仓库分发的 ChineseSimplified.isl
;        （Inno Setup 官方翻译，维护者 Zhenghan Yang），英文用 Inno 自带的
;        Default.isl；Inno 按系统 UI 语言自动选择，中文系统直接显示中文向导。
;
;  权限：PrivilegesRequired=admin —— 安装包必须由管理员运行（写入 Program Files、
;        静默安装 OpenSC 的 MSI 都需要），双击时由 Windows 直接弹出 UAC 提权。
;        主程序 SmartCardAPP.exe 自带 requireAdministrator 清单（建卡要管理员），
;        因此安装完成后启动它还会再弹一次 UAC（对应 [Run] 条目必须带 shellexec）；
;        SSH 密钥代理属于托盘程序，
;        按原用户身份启动、不继承管理员权限。
;
;  组件（向导里可勾选，见 [Components]）：
;    · OpenSC（默认勾选）：静默安装随包分发的 OpenSC-0.25.1_win64-Light.msi，
;      并跳过它的开始菜单快捷方式（REMOVE=OpenSC_menu）。程序读卡用到的
;      {app}\OpenSC 工具目录与这个 MSI 无关，始终随程序主体安装；
;    · WinCryptSSHAgent（默认不勾选）：部署随包分发的 SSH 密钥代理
;      （SSHCardAgent.exe）。它的快捷方式不默认创建、安装后也不默认启动，
;      开机自启改由程序「系统设置 - 启动与托盘」管理；
;    · Visual C++ 2015-2022 x64 运行库（随包分发）：缺少时始终静默安装。
;
;  安装完成后可勾选（都默认不勾）：访问项目主页（GitHub）；主程序默认勾选。
;
;  需要 Inno Setup 6.5 或更高版本（UTF-8 无 BOM 脚本 + x64compatible；
;  ChineseSimplified.isl 与编译器自带的 Default.isl 同为 “6.5.0+” 语言文件级别，
;  用更低版本的编译器会出现语言文件版本不匹配的告警/错误）
; =============================================================================

#define AppName "TPM VSC管理"
#define AppNameEn "TPM Virtual Smart Card Manager"
#define AppPublisher "Pikachu Ren"
#define AppUrl "https://github.com/PIKACHUIM/TPMSmartCard"
#define AppReleasesUrl "https://github.com/PIKACHUIM/TPMSmartCard/releases"

; ---- 版本号 ---------------------------------------------------------------
#define AppVersion GetEnv("TPMSMART_VERSION")
#if Len(AppVersion) == 0
  #define AppVersion "1.6.0"
#endif

#define Version4 GetEnv("TPMSMART_VERSION4")
#if Len(Version4) == 0
  #define Version4 "1.6.0.0"
#endif

; ---- 产物名 ---------------------------------------------------------------
#define PackageName GetEnv("TPMSMART_PACKAGENAME")
#if Len(PackageName) == 0
  #define PackageName "TPMSmartCard-win64"
#endif

; ---- cx_Freeze 输出目录 ---------------------------------------------------
#define BuildDir GetEnv("TPMSMART_BUILDDIR")
#if Len(BuildDir) == 0
  #define BuildDir "build\exe.win-amd64-3.11"
#endif

; ---- 随包分发的依赖 -------------------------------------------------------
#define OpenScMsi "OpenSC-0.25.1_win64-Light.msi"
#define VcRedistExe "VC_redist.x64.exe"
#define VcRedistPath "Setups\Visual C++ Redistributable for Visual Studio 2015-2022 x64\VC_redist.x64.exe"

[Setup]
; AppId 保持恒定，后续版本才能正确覆盖升级
AppId={{57C60B14-6EF3-4FAC-BD01-7CC47679A32D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppReleasesUrl}
VersionInfoVersion={#Version4}
VersionInfoProductVersion={#Version4}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppNameEn}
VersionInfoDescription={#AppNameEn} Setup
VersionInfoCopyright=Copyright (C) {#AppPublisher}
DefaultDirName={autopf}\{#AppNameEn}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\SmartCardAPP.exe
UninstallDisplayName={#AppName}
LicenseFile=LICENSE
OutputDir=dist
OutputBaseFilename={#PackageName}-setup
SetupIconFile=Config\iconer\icon02.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
AllowNoIcons=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
; 默认安装类型 = Full：Inno 取 [Types] 第一个条目作为默认类型（Full 在首位），
; 安装 OpenSC / 写入 Program Files 都需要管理员
PrivilegesRequired=admin
; 本产物基于 Python 3.11 x64 构建，实际需要 Windows 8.1 及以上
MinVersion=6.3
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 注册 .tsb 文件类型关联后需要通知外壳刷新（否则资源管理器不会立刻认图标）
ChangesAssociations=yes
SetupLogging=yes

[Languages]
; 中文放在第一位：Inno 会按系统 UI 语言自动匹配，匹配不到时才弹语言选择框
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
; 界面文字按向导语言取用；{#AppName} 等编译期常量同样会被替换
english.AppShortcut=TPM Virtual Smart Card Manager
english.AgentShortcut=SSH Key Agent
english.GroupTasks=Additional tasks:
english.TaskAgentIcon=Create Start Menu and desktop shortcuts for the SSH key agent
english.RunAgent=Start the SSH key agent
english.RunApp=Run TPM Virtual Smart Card Manager
english.RunGithub=Open the project home page (GitHub)
english.TypeFull=Full installation
english.TypeCustom=Custom installation
english.CompOpenSc=OpenSC smart card middleware (recommended)
english.CompAgent=SSH key agent (WinCryptSSHAgent)
english.StatusVcRedist=Installing Microsoft Visual C++ 2015-2022 runtime...
english.StatusOpenSc=Installing OpenSC (smart card middleware)...
english.ItemLine=%1: %2
english.ItemVcRedist=Visual C++ 2015-2022 runtime
english.ItemOpenSc=OpenSC
english.StateSkipped=already installed, skipped
english.StateInstalled=installed
english.StateFailed=installation failed (exit code %1)
english.StateUnselected=not selected, skipped
english.PrereqWarnTitle=Some dependencies were not installed
english.PrereqWarnBody=Setup will continue. You can retry from the app's Settings page after installation, or run the installer manually (OpenSC is in the OpenSC folder of the app directory).
chinesesimplified.AppShortcut={#AppName}
chinesesimplified.AgentShortcut=SSH 密钥代理
chinesesimplified.GroupTasks=附加任务：
chinesesimplified.TaskAgentIcon=创建 SSH 密钥代理的开始菜单与桌面快捷方式
chinesesimplified.RunAgent=启动 SSH 密钥代理
chinesesimplified.RunApp=运行 {#AppName}
chinesesimplified.RunGithub=访问项目主页（GitHub）
chinesesimplified.TypeFull=完整安装
chinesesimplified.TypeCustom=自定义安装
chinesesimplified.CompOpenSc=OpenSC 智能卡中间件（推荐）
chinesesimplified.CompAgent=SSH 密钥代理（WinCryptSSHAgent）
chinesesimplified.StatusVcRedist=正在安装 Visual C++ 2015-2022 运行库...
chinesesimplified.StatusOpenSc=正在安装 OpenSC（智能卡中间件）...
chinesesimplified.ItemLine=%1：%2
chinesesimplified.ItemVcRedist=Visual C++ 2015-2022 运行库
chinesesimplified.ItemOpenSc=OpenSC
chinesesimplified.StateSkipped=已安装，跳过
chinesesimplified.StateInstalled=安装完成
chinesesimplified.StateFailed=安装失败（退出码 %1）
chinesesimplified.StateUnselected=未选择安装，跳过
chinesesimplified.PrereqWarnTitle=部分依赖未能自动安装
chinesesimplified.PrereqWarnBody=安装程序将继续。安装完成后可在程序「系统设置」中重试，或手动运行安装包（OpenSC 位于程序目录的 OpenSC 文件夹）。

[Types]
; 默认类型是第一个条目 Full（Inno 没有单独的 DefaultType 指令）；带 iscustom 的
; Custom 让用户仍可手动勾选/取消组件（勾选 SSH 代理时 Setup 会自动切到「自定义」）。
Name: "full"; Description: "{cm:TypeFull}"
Name: "custom"; Description: "{cm:TypeCustom}"; Flags: iscustom

[Components]
; OpenSC 属于 Full 类型 → 默认勾选；SSH 代理不属于任何类型 → 默认不勾选
Name: "opensc"; Description: "{cm:CompOpenSc}"; Types: full
Name: "agent"; Description: "{cm:CompAgent}"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; 代理的快捷方式默认不创建（选了「SSH 密钥代理」组件才可选）；
; 开机自启不再由安装包创建启动文件夹快捷方式，改由程序「系统设置 - 启动与托盘」管理
Name: "agenticon"; Description: "{cm:TaskAgentIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Components: agent; Flags: unchecked

[Files]
; 程序主体（cx_Freeze 输出）；SSH 代理是可选项，单独作为一条目的（见下）
Source: "{#BuildDir}\*"; Excludes: "SSHCardAgent.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; SSH 密钥代理：勾选「SSH 密钥代理」组件时才复制
Source: "{#BuildDir}\SSHCardAgent.exe"; DestDir: "{app}"; Components: agent; Flags: ignoreversion skipifsourcedoesntexist
; TPMImport：程序运行时以相对路径调用 Import\TPMImport.exe
; 只收顶层运行时文件（不递归，避免把 Import\TPMImport 源码工程一起打进去）
Source: "Import\TPMImport.exe"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Import\*.dll"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Import\*.json"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
; 依赖安装包：不在安装阶段复制，由 [Code] 按需解包后静默安装
Source: "OpenSC\{#OpenScMsi}"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#VcRedistPath}"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{cm:AppShortcut}"; Filename: "{app}\SmartCardAPP.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{cm:AppShortcut}"; Filename: "{app}\SmartCardAPP.exe"; WorkingDir: "{app}"; Tasks: desktopicon
; SSH 代理的快捷方式：要「装了代理」且「勾了创建快捷方式」两条都满足才创建
Name: "{group}\{cm:AgentShortcut} (WinCryptSSHAgent)"; Filename: "{app}\SSHCardAgent.exe"; WorkingDir: "{app}"; Components: agent; Tasks: agenticon
Name: "{autodesktop}\{cm:AgentShortcut}"; Filename: "{app}\SSHCardAgent.exe"; WorkingDir: "{app}"; Components: agent; Tasks: agenticon

[Registry]
; .tsb（智能卡备份文件）的文件类型关联中与安装路径相关的部分：
;   · 图标用主程序图标；
;   · 双击打开 = 用主程序还原（主程序收到 "%1" 后直接进入还原流程）。
; 与安装路径无关的部分（.tsb -> ProgID、Content Type 等）在 Config\tsb.reg，
; 安装时用 reg import 合并（见下面 [Run] 段）。
Root: HKA; Subkey: "TPMSmartCard.Backup\DefaultIcon"; ValueType: string; ValueData: "{app}\Config\iconer\icon02.ico"; Flags: uninsdeletevalue
Root: HKA; Subkey: "TPMSmartCard.Backup\shell\open\command"; ValueType: string; ValueData: """{app}\SmartCardAPP.exe"" ""%1"""; Flags: uninsdeletevalue

[Run]
; 合并 .tsb 文件类型注册（Config\tsb.reg）
Filename: "{cmd}"; Parameters: "/c reg import ""{app}\Config\tsb.reg"""; Flags: runhidden
; 主程序自带 requireAdministrator 清单（BuildPackage.py 里 uac_admin=True）：
; runasoriginaluser 只表示「以原用户身份」，shellexec 才让条目经过 Windows 外壳
; （AppInfo 服务）——由外壳负责弹 UAC 完成提权。
; 少了 shellexec 会走 CreateProcess 路径：对清单要求提升的程序直接失败（错误 740，
; ERROR_ELEVATION_REQUIRED，不会弹 UAC），表现为「安装完成后点启动没反应 / 没有管理员权限」。
Filename: "{app}\SmartCardAPP.exe"; Description: "{cm:RunApp}"; Flags: postinstall nowait runasoriginaluser shellexec
; SSH 密钥代理是托盘程序，按原用户身份启动（不继承管理员权限）；
; 默认不勾选，且没勾选「SSH 密钥代理」组件（没装代理）时直接跳过
Filename: "{app}\SSHCardAgent.exe"; Description: "{cm:RunAgent}"; Components: agent; Flags: postinstall nowait runasoriginaluser unchecked skipifdoesntexist
; 项目主页：默认不勾选，勾选后交给外壳用默认浏览器打开（shellexec 支持 URL）
Filename: "{#AppUrl}"; Description: "{cm:RunGithub}"; Flags: postinstall nowait shellexec unchecked

[UninstallRun]
; 主程序常驻托盘、代理与 Web 服务常驻后台：卸载前先结束，避免文件占用
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SmartCardAPP.exe"; Flags: runhidden; RunOnceId: "StopSmartCardApp"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SSHCardAgent.exe"; Flags: runhidden; RunOnceId: "StopSshAgent"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SmartCardWEB.exe"; Flags: runhidden; RunOnceId: "StopWebServer"
; 清理「系统设置 - 启动与托盘」写入的自启（计划任务与启动项；不存在时忽略）
Filename: "{cmd}"; Parameters: "/c schtasks /delete /tn ""TPMSmartCard"" /f"; Flags: runhidden; RunOnceId: "DelAppStartTask"
Filename: "{cmd}"; Parameters: "/c schtasks /delete /tn ""WinCryptSSHAgent"" /f"; Flags: runhidden; RunOnceId: "DelAgentStartTask"
Filename: "{cmd}"; Parameters: "/c reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v TPMSmartCard /f"; Flags: runhidden; RunOnceId: "DelAppStartRun"
Filename: "{cmd}"; Parameters: "/c reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v WinCryptSSHAgent /f"; Flags: runhidden; RunOnceId: "DelAgentStartRun"
; 移除 .tsb 文件类型关联（.tsb 是本工具自己的备份格式）
Filename: "{cmd}"; Parameters: "/c reg delete ""HKCR\TPMSmartCard.Backup"" /f"; Flags: runhidden; RunOnceId: "UnregisterTsbProgId"
Filename: "{cmd}"; Parameters: "/c reg delete ""HKCR\.tsb"" /f"; Flags: runhidden; RunOnceId: "UnregisterTsbExt"

[InstallDelete]
; 覆盖升级时清掉旧的 cx_Freeze 运行库目录，避免残留旧模块
Type: filesandordirs; Name: "{app}\lib"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\Caches"

[Code]
const
  VCRUNTIME_KEY = 'SOFTWARE\Microsoft\DevDiv\vc\Servicing\14.0\RuntimeMinimum';
  VCRUNTIME_MIN = '14.30.30704';

var
  PrereqLog: String;
  PrereqFailed: Boolean;

{ 比较形如 14.44.35211.0 的版本号：A >= B 返回 True }
function VersionAtLeast(const A, B: String): Boolean;
var
  I, J, NumA, NumB: Integer;
begin
  I := 1;
  J := 1;
  Result := True;
  while (I <= Length(A)) or (J <= Length(B)) do
  begin
    NumA := 0;
    NumB := 0;
    while (I <= Length(A)) and (A[I] <> '.') do
    begin
      if (A[I] >= '0') and (A[I] <= '9') then
        NumA := NumA * 10 + (Ord(A[I]) - Ord('0'));
      Inc(I);
    end;
    while (J <= Length(B)) and (B[J] <> '.') do
    begin
      if (B[J] >= '0') and (B[J] <= '9') then
        NumB := NumB * 10 + (Ord(B[J]) - Ord('0'));
      Inc(J);
    end;
    if NumA <> NumB then
    begin
      Result := NumA > NumB;
      Exit;
    end;
    Inc(I);
    Inc(J);
  end;
end;

{ VC++ 2015-2022 运行库是否已满足最低版本 }
function IsVcRedistInstalled(): Boolean;
var
  Value: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM64, VCRUNTIME_KEY, 'Version', Value) then
    Result := VersionAtLeast(Value, VCRUNTIME_MIN);
end;

{ OpenSC 是否已安装（与程序自身的检测方式一致） }
function IsOpenScInstalled(): Boolean;
begin
  Result := DirExists(ExpandConstant('{commonpf}\OpenSC Project\OpenSC')) or
            DirExists(ExpandConstant('{commonpf32}\OpenSC Project\OpenSC'));
end;

{ 执行并等待结束，返回退出码（启动失败返回 -1） }
function RunPrereqFile(const FullPath, Params, StatusText: String): Integer;
begin
  WizardForm.StatusLabel.Caption := StatusText;
  Result := -1;
  if not Exec(FullPath, Params, '', SW_SHOWNORMAL, ewWaitUntilTerminated, Result) then
    Result := -1;
end;

{ 执行临时目录里已解包的依赖安装包 }
function RunPrereq(const FileName, Params, StatusText: String): Integer;
begin
  Result := RunPrereqFile(ExpandConstant('{tmp}\') + FileName, Params, StatusText);
end;

{ MSI / 运行库安装的“成功”退出码：0 成功；1638/1639 已安装；3010/1641 需要重启 }
function IsInstallSuccess(const Code: Integer): Boolean;
begin
  Result := (Code = 0) or (Code = 1638) or (Code = 1639) or
            (Code = 3010) or (Code = 1641);
end;

{ 取当前向导语言下的自定义消息（cm 常量在运行时可展开） }
function CM(const Name: String): String;
begin
  Result := ExpandConstant('{cm:' + Name + '}');
end;

{ 组装一行依赖处理结果，如 “· OpenSC：安装完成” }
function PrereqNote(const ItemName, StateText: String): String;
begin
  Result := '· ' + FmtMessage(CM('ItemLine'), [ItemName, StateText]) + #13#10;
end;

{ 退出码对应的状态文字 }
function PrereqState(const Code: Integer): String;
begin
  if IsInstallSuccess(Code) then
    Result := CM('StateInstalled')
  else
    Result := FmtMessage(CM('StateFailed'), [IntToStr(Code)]);
end;

function InstallDependencies(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  PrereqLog := '';
  PrereqFailed := False;

  { 1) Visual C++ 运行库 }
  if IsVcRedistInstalled() then
    PrereqLog := PrereqLog + PrereqNote(CM('ItemVcRedist'), CM('StateSkipped'))
  else
  begin
    ExtractTemporaryFile('{#VcRedistExe}');
    Code := RunPrereq('{#VcRedistExe}', '/install /quiet /norestart', CM('StatusVcRedist'));
    PrereqLog := PrereqLog + PrereqNote(CM('ItemVcRedist'), PrereqState(Code));
    if IsInstallSuccess(Code) then
    begin
      if (Code = 3010) or (Code = 1641) then
        NeedsRestart := True;
    end
    else
      PrereqFailed := True;
  end;

  { 2) OpenSC（智能卡中间件）：没勾选组件时跳过，之后可在程序「系统设置」里安装 }
  if not WizardIsComponentSelected('opensc') then
    PrereqLog := PrereqLog + PrereqNote(CM('ItemOpenSc'), CM('StateUnselected'))
  else if IsOpenScInstalled() then
    PrereqLog := PrereqLog + PrereqNote(CM('ItemOpenSc'), CM('StateSkipped'))
  else
  begin
    ExtractTemporaryFile('{#OpenScMsi}');
    { REMOVE=OpenSC_menu：不创建 OpenSC 的开始菜单快捷方式（其余功能照常安装） }
    Code := RunPrereqFile(ExpandConstant('{sys}\msiexec.exe'),
      '/i "' + ExpandConstant('{tmp}\') + '{#OpenScMsi}' + '" /qn /norestart' +
      ' REMOVE=OpenSC_menu' +
      ' /l*v "' + ExpandConstant('{tmp}\opensc-install.log') + '"',
      CM('StatusOpenSc'));
    PrereqLog := PrereqLog + PrereqNote(CM('ItemOpenSc'), PrereqState(Code));
    if IsInstallSuccess(Code) then
    begin
      if (Code = 3010) or (Code = 1641) then
        NeedsRestart := True;
    end
    else
      PrereqFailed := True;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  InstallDependencies(NeedsRestart);
  if PrereqFailed then
    MsgBox(CM('PrereqWarnTitle') + #13#10 + #13#10 + PrereqLog + #13#10 +
           CM('PrereqWarnBody'), mbInformation, MB_OK);
end;
