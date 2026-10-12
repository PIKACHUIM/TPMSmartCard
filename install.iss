; =============================================================================
;  TPM 虚拟智能卡管理工具 —— Inno Setup 安装包脚本
;
;  本地编译：  iscc install.iss
;  CI 编译：   .github/workflows/build.yml（自动设置下列环境变量）
;
;  可选环境变量（都有默认值，本地直接编译也能用）：
;    TPMSMART_VERSION      显示版本号，如 1.6 / 1.6.2026.1012（默认 1.5.0）
;    TPMSMART_VERSION4     写入 exe 版本资源的 4 段版本号，如 1.6.0.0（默认 1.5.0.0）
;    TPMSMART_PACKAGENAME  产物基础名，如 TPMSmartCard-1.6-win64（默认 TPMSmartCard-win64）
;    TPMSMART_BUILDDIR     cx_Freeze 输出目录（默认 build\exe.win-amd64-3.11）
;
;  安装过程会自动完成：
;    1) 静默安装随包分发的 OpenSC（OpenSC-0.25.1_win64-Light.msi）
;    2) 缺少时静默安装 Visual C++ 2015-2022 x64 运行库（随包分发）
;    3) 部署随包分发的 SSH 密钥代理 WinCryptSSHAgent（SSHCardAgent.exe），
;       并按需创建开机自启快捷方式、安装完成后启动
;
;  需要 Inno Setup 6.3 或更高版本（UTF-8 无 BOM 脚本 + x64compatible）
; =============================================================================

#define AppName "TPM 虚拟智能卡管理工具"
#define AppNameEn "TPM Virtual Smart Card Manager"
#define AppPublisher "Pikachu Ren"
#define AppUrl "https://github.com/PIKACHUIM/TPMSmartCard"
#define AppReleasesUrl "https://github.com/PIKACHUIM/TPMSmartCard/releases"

; ---- 版本号 ---------------------------------------------------------------
#define AppVersion GetEnv("TPMSMART_VERSION")
#if Len(AppVersion) == 0
  #define AppVersion "1.5.0"
#endif

#define Version4 GetEnv("TPMSMART_VERSION4")
#if Len(Version4) == 0
  #define Version4 "1.5.0.0"
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
; 安装 OpenSC / 写入 Program Files 都需要管理员
PrivilegesRequired=admin
; 本产物基于 Python 3.11 x64 构建，实际需要 Windows 8.1 及以上
MinVersion=6.3
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "agentstartup"; Description: "开机时自动启动 SSH 密钥代理（WinCryptSSHAgent）/ Start the SSH agent at logon"; GroupDescription: "附加任务 / Additional tasks:"; Flags: checkedonce

[Files]
; 程序主体（cx_Freeze 输出）
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; TPMImport：程序运行时以相对路径调用 Import\TPMImport.exe
; 只收顶层运行时文件（不递归，避免把 Import\TPMImport 源码工程一起打进去）
Source: "Import\TPMImport.exe"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Import\*.dll"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
Source: "Import\*.json"; DestDir: "{app}\Import"; Flags: ignoreversion skipifsourcedoesntexist
; 依赖安装包：不在安装阶段复制，由 [Code] 按需解包后静默安装
Source: "OpenSC\{#OpenScMsi}"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#VcRedistPath}"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\SmartCardAPP.exe"; WorkingDir: "{app}"
Name: "{group}\SSH 密钥代理 (WinCryptSSHAgent)"; Filename: "{app}\SSHCardAgent.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SmartCardAPP.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{autodesktop}\SSH 密钥代理"; Filename: "{app}\SSHCardAgent.exe"; WorkingDir: "{app}"; Tasks: desktopicon
; 开机自启：与旧安装包（Advanced Installer 的 StartupFolder 快捷方式）行为一致
Name: "{commonstartup}\SSH 密钥代理"; Filename: "{app}\SSHCardAgent.exe"; WorkingDir: "{app}"; Tasks: agentstartup

[Run]
Filename: "{app}\SSHCardAgent.exe"; Description: "启动 SSH 密钥代理 / Start the SSH agent"; Flags: postinstall nowait runasoriginaluser
Filename: "{app}\SmartCardAPP.exe"; Description: "运行 {#AppName}"; Flags: postinstall nowait runasoriginaluser

[UninstallRun]
; 代理与 Web 服务常驻后台，卸载前先结束，避免文件占用
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SSHCardAgent.exe"; Flags: runhidden; RunOnceId: "StopSshAgent"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SmartCardWEB.exe"; Flags: runhidden; RunOnceId: "StopWebServer"

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

function InstallDependencies(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  PrereqLog := '';
  PrereqFailed := False;

  { 1) Visual C++ 运行库 }
  if IsVcRedistInstalled() then
    PrereqLog := PrereqLog + '· Visual C++ 2015-2022 运行库：已安装，跳过' + #13#10
  else
  begin
    ExtractTemporaryFile('{#VcRedistExe}');
    Code := RunPrereq('{#VcRedistExe}', '/install /quiet /norestart',
                      '正在安装 Visual C++ 2015-2022 运行库...');
    if IsInstallSuccess(Code) then
    begin
      PrereqLog := PrereqLog + '· Visual C++ 2015-2022 运行库：已安装' + #13#10;
      if (Code = 3010) or (Code = 1641) then
        NeedsRestart := True;
    end
    else
    begin
      PrereqFailed := True;
      PrereqLog := PrereqLog + Format('· Visual C++ 2015-2022 运行库：安装失败（退出码 %d）', [Code]) + #13#10;
    end;
  end;

  { 2) OpenSC（智能卡中间件） }
  if IsOpenScInstalled() then
    PrereqLog := PrereqLog + '· OpenSC：已安装，跳过' + #13#10
  else
  begin
    ExtractTemporaryFile('{#OpenScMsi}');
    Code := RunPrereqFile(ExpandConstant('{sys}\msiexec.exe'),
      '/i "' + ExpandConstant('{tmp}\') + '{#OpenScMsi}' + '" /qn /norestart' +
      ' /l*v "' + ExpandConstant('{tmp}\opensc-install.log') + '"',
      '正在安装 OpenSC（智能卡中间件）...');
    if IsInstallSuccess(Code) then
    begin
      PrereqLog := PrereqLog + '· OpenSC：已安装' + #13#10;
      if (Code = 3010) or (Code = 1641) then
        NeedsRestart := True;
    end
    else
    begin
      PrereqFailed := True;
      PrereqLog := PrereqLog + Format('· OpenSC：安装失败（退出码 %d）', [Code]) + #13#10;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  InstallDependencies(NeedsRestart);
  if PrereqFailed then
    MsgBox('以下依赖组件未能自动安装：' + #13#10 + #13#10 + PrereqLog + #13#10 +
           '安装程序将继续，安装完成后可在程序「系统设置」中重试，' +
           '或手动运行安装包（OpenSC 位于程序目录的 OpenSC 文件夹）。',
           mbInformation, MB_OK);
end;
