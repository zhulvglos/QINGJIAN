; ============================================================
; 轻笺 (LightNote) v0.4 - Inno Setup 安装程序
;
; 使用方法：
;   1. 安装 Inno Setup 6.x: https://jrsoftware.org/isdl.php
;   2. 双击运行: iscc installer.iss
;   3. 安装包输出到: installer\轻笺_v0.4.0_安装包.exe
; ============================================================

#define AppName "轻笺"
#define AppVersion "0.4.0"
#define AppPublisher "LightNote"
#define AppExeName "Qingjian.exe"
#define DefaultDirName "{autopf}\轻笺"
#define ProjectRoot ".."

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={#DefaultDirName}
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=轻笺_v{#AppVersion}_安装包
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=installer.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
MinVersion=6.1sp1
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=本地优先的 Windows 桌面信息管理工具
VersionInfoCopyright=Copyright (C) 2025 LightNote

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu folder"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; 主程序
Source: "{#ProjectRoot}\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; 语音组件安装脚本（可选功能，用户按需运行）
Source: "{#ProjectRoot}\install_voice.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\install_sensevoice.bat"; DestDir: "{app}"; Flags: ignoreversion

; 辅助脚本
Source: "{#ProjectRoot}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs

; CI 工作流
Source: "{#ProjectRoot}\.github\workflows\*"; DestDir: "{app}\.github\workflows"; Flags: ignoreversion recursesubdirs

; 录音回答知识库 — 用户自行添加内容
Source: "{#ProjectRoot}\录音回答知识库\知识库说明.txt"; DestDir: "{app}\录音回答知识库"; Flags: ignoreversion onlyifdoesntexist
Source: "{#ProjectRoot}\录音回答知识库\语音功能安装说明.txt"; DestDir: "{app}\录音回答知识库"; Flags: ignoreversion onlyifdoesntexist

[Directories]
Name: "{app}\logs"
Name: "{app}\recordings"
Name: "{localappdata}\轻笺"
Name: "{localappdata}\轻笺\recordings"
Name: "{localappdata}\轻笺\news_cache"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autostartmenu}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startmenuicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// 安装前检查
function InitializeSetup(): Boolean;
begin
  Result := true;
end;
