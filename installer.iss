; ============================================================================
;  玉用去水印 —— Inno Setup 安装脚本
;  编译：ISCC.exe installer.iss
;  产出：dist\玉用去水印_v1.0.0_安装包.exe
; ============================================================================

#define MyAppName "玉用去水印"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "张洪坤"
#define MyAppExeName "玉用去水印.exe"
#define MyAppId "YuYongQuShuiYin"

[Setup]
AppId={{8F3A1C64-7B2E-4D51-9E0A-3C9F51A7B2E4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=dist
OutputBaseFilename={#MyAppName}_v{#MyAppVersion}_安装包
SetupIconFile=app\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0
ShowLanguageDialog=no
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinese.CreateDesktopIcon=创建桌面快捷方式
chinese.AutoStart=开机自动启动（推荐）
chinese.LaunchAfter=安装完成后立即运行 {#MyAppName}
chinese.AdditionalIcons=附加快捷方式：
chinese.AutoStartTask=开机自启动

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart";   Description: "{cm:AutoStart}";       GroupDescription: "{cm:AdditionalIcons}"

[Files]
; onedir 打包产物整体拷贝
Source: "app\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}";          Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";         Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 开机自启（当前用户，无需管理员）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: """{app}\{#MyAppExeName}"" --autostart"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchAfter}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前先结束进程，避免文件占用导致卸载不干净
Filename: "{cmd}"; Parameters: "/c taskkill /f /im ""{#MyAppExeName}"""; \
    Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\assets"
Type: dirifempty;     Name: "{app}"

[Code]
// 安装前检测是否已经在运行
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if Exec(ExpandConstant('{cmd}'), '/c tasklist /fi "imagename eq {#MyAppExeName}" | find /i "{#MyAppExeName}" >nul', '',
          SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
    begin
      if MsgBox('检测到「{#MyAppName}」正在运行，需要先关闭它才能继续安装。' + #13#10 +
                '是否现在自动关闭并继续？', mbConfirmation, MB_YESNO) = IDYES then
      begin
        Exec(ExpandConstant('{cmd}'), '/c taskkill /f /im "{#MyAppExeName}"', '', SW_HIDE,
             ewWaitUntilTerminated, ResultCode);
        Result := True;
      end
      else
        Result := False;
    end;
  end;
end;
