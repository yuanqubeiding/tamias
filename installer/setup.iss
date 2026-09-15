; ============================================================
; 栗栗（Tamias）桌面智能助手 — Inno Setup 安装脚本
; ============================================================
; 编译此脚本需要安装 Inno Setup：
;   下载地址：https://jrsoftware.org/isdl.php
;
; 编译前准备：
;   1. 运行 python build.py 生成 dist/tamias/ 文件夹
;   2. 在 Inno Setup Compiler 中打开此 .iss 文件
;   3. 点击 Compile（或运行 iscc setup.iss）
;
; 输出：installer/tamias_setup.exe
; ============================================================

#define MyAppName "栗栗桌面助手"
#define MyAppNameEn "Tamias"
#define MyAppVersion "0.1.5"
#define MyAppPublisher "Tamias Team"
#define MyAppURL "https://github.com/yuanqubeiding"
#define MyAppExeName "tamias.exe"

; 源文件路径（相对于此 .iss 文件）
; PyInstaller 输出在 dist/tamias/
#define SourcePath "..\dist\tamias"

[Setup]
; 安装程序基本信息
AppId={{4698BD4E-996C-487A-BE18-5CB29BCB726F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 默认安装路径（用英文目录名 Tamias，避开中文路径导致 Live2D/QWebEngine 白屏）
DefaultDirName={autopf}\{#MyAppNameEn}

; 不继承「上次安装目录」。Inno 默认会记住上次装到哪（写注册表），
; 若用户旧版装到中文路径（如 D:\栗栗桌面助手），新版安装器也会默认沿用那个中文路径，
; 导致装进中文目录 → Live2D 白屏。关掉后每次安装都用上面 {autopf}\Tamias 英文默认路径。
UsePreviousAppDir=no

; 开始菜单文件夹名
DefaultGroupName={#MyAppName}

; 禁止用户修改安装目录（可选。如果允许修改，注释掉下面这行）
; DisableDirPage=yes

; 安装程序输出
OutputDir=.
OutputBaseFilename=tamias_setup_v{#MyAppVersion}

; 安装程序图标（如果有 .ico 文件）
; SetupIconFile=..\tamias\resources\tamias.ico

; 压缩方式
Compression=lzma2
SolidCompression=yes

; 权限（需要管理员权限写入 Program Files）
PrivilegesRequired=admin

; RedirectionGuard=no：关掉安装器的 RedirectionGuard 缓解（Inno Setup 6.7 起默认开启）。
; 该缓解会给安装器进程开 EnforceRedirectionTrust，专拦「非提权进程建的 junction/symlink
; 被遍历」；而 [Run] postinstall 从安装器进程树拉起栗栗 → node.exe 一路继承这个 flag，
; 导致 node 遍历不了 %APPDATA%\Tamias\dsh 里的 node_modules junction（报 untrusted
; mount point → Cannot find package → plugin tree failed），症状就是「装完第一次干活
; 引擎连不上、重启电脑才好」。关掉后首启即可用——本安装器写目录
; 全程受控、无不可信外源能塞重定向，风险可接受。
RedirectionGuard=no

; 安装程序外观
WizardStyle=modern
WizardResizable=no

; 窗口大小
WizardSizePercent=120,120

; 卸载时先关闭运行中的程序
CloseApplications=yes
CloseApplicationsFilter=*.exe

; 许可协议文件（如果有的话）
; LicenseFile=..\LICENSE.txt

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; 覆盖安装完成页文字：RedirectionGuard=no 之后首启即可用；但干活引擎冷启动要加载
; 3 万+ 文件，首启可能等几秒到一两分钟，状态栏会显示「未连接」——点一下「刷新」
; 就能连上，不用重启电脑。提前告知，别让用户干等/以为坏了。
; 注：这是全局覆盖，英文安装也会显示这句中文——栗栗中文优先，可接受；要细分再拆语言前缀。
FinishedLabel=安装完成！%n%n栗栗首次启动时干活引擎要加载较多文件，可能等几秒到一两分钟；若状态栏仍显示「未连接」，点一下「刷新」按钮即可连上。

[Tasks]
; 创建桌面快捷方式
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

; 注意：不再提供「开机自启动」安装选项。
; 开机自启动改由应用内设置管理（右键栗栗 → 设置 / 系统托盘 → 设置里的「开机自启动」开关，
; 写注册表 HKCU\...\Run 键）。之前这里的 startup 任务没接任何 Icon/Registry 条目，
; 勾了也是空转（不会真建启动项），反而让用户误以为装了就自启——已移除。

[Files]
; 主程序和所有依赖文件（含 runtime/node + runtime/dsh + config.yaml 模板，全部随包）
Source: "{#SourcePath}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 注意：用户实际配置 config.yaml 已外移到 %APPDATA%\Tamias\（首次运行自动生成，
; 覆盖安装 / 卸载都不动它）。这里不再单独 onlyifdoesntexist 装到 {app}。

; VC++ 运行库（如果需要的话，通常 PyQt6 自带）
; Source: "vcredist\*"; DestDir: "{tmp}"; Flags: deleteafterinstall

[InstallDelete]
; 升级清理：删除旧版本遗留、新版不再包含的文件（孤儿文件）。
; 覆盖安装（ignoreversion）只会替换同名文件，不会清理「旧版有、新版没有」的残留，
; 所以每次改版删文件 / 改名时，都要在这里补一行，避免旧文件残留在用户机器上。
; 例：从「元元 yuan_yuan」改名「栗栗 tamias」之前的旧可执行文件。
Type: files; Name: "{app}\yuan_yuan.exe"

[UninstallDelete]
; 卸载时清掉 QWebEngine（立绘 Chromium）的本地缓存目录。
; 栗栗运行时 app.setApplicationName("栗栗桌面助手")，QWebEngine 默认把缓存写到
; %LOCALAPPDATA%\栗栗桌面助手（Cache/GPUCache 等），不含用户数据、重装会自动重建，
; 但卸载不删会残留（测试用户反馈「卸载不干净」）。卸载前 [UninstallRun] 已先杀进程防锁。
Type: filesandordirs; Name: "{localappdata}\栗栗桌面助手"

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

; 桌面快捷方式
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后启动栗栗
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载前关闭栗栗进程
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden
; 清 dsh 残留进程 + QWebEngine（立绘 Chromium）子进程 + 开机自启动
; （合并一条 cmd，末尾 exit 0 保证「没 node 进程 / 没自启键」时不报错弹窗）。
; QtWebEngineProcess.exe 是栗栗 Live2D 立绘的 Chromium 子进程，父进程被强杀后可能残留，
; 并锁着 %LOCALAPPDATA%\栗栗桌面助手 的缓存文件，不先杀干净 [UninstallDelete] 删不掉。
Filename: "{cmd}"; Parameters: "/c taskkill /f /im node.exe & taskkill /f /im QtWebEngineProcess.exe & reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v Tamias /f & exit 0"; Flags: runhidden

[Code]
// ============================================================
// 自定义安装逻辑
// ============================================================

// 卸载数据选择对话框的全局勾选框（CurUninstallStepChanged 里创建，各按钮事件读写）
var
  UninstallDataForm: TForm;
  ChkConfig: TNewCheckBox;
  ChkData: TNewCheckBox;
  ChkDsh: TNewCheckBox;
  ChkLogs: TNewCheckBox;

// 检查是否满足最低系统要求
function InitializeSetup: Boolean;
begin
  // 检查 Windows 版本（至少 Windows 10）
  if GetWindowsVersion < $0A000000 then
  begin
    MsgBox('栗栗需要 Windows 10 或更高版本。' + #13#10 +
           '检测到您的系统版本过低，安装无法继续。',
           mbError, MB_OK);
    Result := False;
    Exit;
  end;

  Result := True;
end;

// 检查路径是否纯 ASCII（含中文/全角字符 = 会导致 Live2D 白屏）
function IsAsciiPath(const S: String): Boolean;
var
  I: Integer;
begin
  Result := True;
  for I := 1 to Length(S) do
    if Ord(S[I]) > 127 then
    begin
      Result := False;
      Exit;
    end;
end;

// 用户在「选择安装目录」页点下一步时校验：中文路径拦下，提示改英文
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    if not IsAsciiPath(ExpandConstant('{app}')) then
    begin
      MsgBox('安装路径包含中文或特殊字符，会导致立绘（Live2D）白屏无法显示。' + #13#10 +
             '请改成纯英文路径，例如 D:\Tamias。', mbError, MB_OK);
      Result := False;
    end;
end;

// 安装前检查是否已有运行中的栗栗
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // 尝试关闭已运行的栗栗
  if Exec('taskkill', '/f /im tamias.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    // 成功关闭或本来就没在运行
  end;

  Result := '';
end;

// ============================================================
// 卸载数据选择：自定义勾选对话框（用户自选要删哪些数据）
// ============================================================

// 「全选」按钮：四项全勾
procedure UninstallSelectAllClick(Sender: TObject);
begin
  ChkConfig.Checked := True;
  ChkData.Checked := True;
  ChkDsh.Checked := True;
  ChkLogs.Checked := True;
end;

// 「全不选」按钮：四项全清
procedure UninstallSelectNoneClick(Sender: TObject);
begin
  ChkConfig.Checked := False;
  ChkData.Checked := False;
  ChkDsh.Checked := False;
  ChkLogs.Checked := False;
end;

// 按勾选删对应的 AppData 数据。
// config.yaml 是文件用 del；data/dsh/logs 是目录用 rmdir /s /q（只删本目录、
// 不穿透 junction，以后 dsh 插件目录就算做成软链也不会误删安装目录的包）。
procedure DeleteSelectedUserData();
var
  ResultCode: Integer;
  BaseDir: String;
begin
  BaseDir := ExpandConstant('{userappdata}\Tamias');
  if ChkConfig.Checked then
    Exec(ExpandConstant('{cmd}'), '/c del /f /q "' + BaseDir + '\config.yaml"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ChkData.Checked then
    Exec(ExpandConstant('{cmd}'), '/c rmdir /s /q "' + BaseDir + '\data"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ChkDsh.Checked then
    Exec(ExpandConstant('{cmd}'), '/c rmdir /s /q "' + BaseDir + '\dsh"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ChkLogs.Checked then
    Exec(ExpandConstant('{cmd}'), '/c rmdir /s /q "' + BaseDir + '\logs"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// 卸载完成后：弹勾选框让用户自选要删的数据（默认全不勾 = 全保留）
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Lbl: TNewStaticText;
  BtnOK: TNewButton;
  BtnAll: TNewButton;
  BtnNone: TNewButton;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 升级重装时 Inno 会静默跑一遍旧卸载器（UninstallSilent=True）再装新版，
    // 这时不该弹「选择删除数据」窗体——否则升级安装过程中会冒出卸载窗体、
    // 甚至触发 Pascal Script 运行时错误（Runtime Error at ...）。
    // 静默卸载（含升级触发的卸载）直接跳过，只在用户手动卸载时才弹窗。
    if UninstallSilent then
      Exit;

    // 修「选择删除数据页超大/全屏」：实测（_scaleunins2.txt）——ShowCaptionBar=False 时
    // CreateCustomForm 会无视传入宽度、按 WizardSizePercent=120 放大（500→600），高 DPI
    // （本机 AppliedDPI=144 / 150%）下再叠一层就成整屏。ShowCaptionBar=True 则宽度正确（500）。
    // 所以①改带标题栏（标题「栗栗 - 选择要删除的数据」也终于能显示）②再显式 ClientWidth/
    // ClientHeight 钉死尺寸，双保险不再被撑爆。
    UninstallDataForm := CreateCustomForm(ScaleX(500), ScaleY(340), True, False);
    UninstallDataForm.ClientWidth := ScaleX(500);
    UninstallDataForm.ClientHeight := ScaleY(340);
    try
      UninstallDataForm.Caption := '栗栗 - 选择要删除的数据';
      UninstallDataForm.Position := poScreenCenter;
      UninstallDataForm.BorderStyle := bsDialog;

      // 顶部说明文字（AutoSize 关掉 + WordWrap + AdjustHeight 按文字自动撑高，不会挤）
      Lbl := TNewStaticText.Create(UninstallDataForm);
      Lbl.Parent := UninstallDataForm;
      Lbl.AutoSize := False;
      Lbl.WordWrap := True;
      Lbl.Top := ScaleY(16);
      Lbl.Left := ScaleX(20);
      Lbl.Width := ScaleX(460);
      Lbl.Caption := '栗栗已卸载。勾选要删除的数据（不勾选会保留，重装后仍可用）：';
      Lbl.AdjustHeight;

      ChkConfig := TNewCheckBox.Create(UninstallDataForm);
      ChkConfig.Parent := UninstallDataForm;
      ChkConfig.Top := ScaleY(84);
      ChkConfig.Left := ScaleX(24);
      ChkConfig.Width := ScaleX(452);
      ChkConfig.Caption := '配置 + API Key（config.yaml）';
      ChkConfig.Checked := False;

      ChkData := TNewCheckBox.Create(UninstallDataForm);
      ChkData.Parent := UninstallDataForm;
      ChkData.Top := ScaleY(124);
      ChkData.Left := ScaleX(24);
      ChkData.Width := ScaleX(452);
      ChkData.Caption := '聊天记录（data）';
      ChkData.Checked := False;

      ChkDsh := TNewCheckBox.Create(UninstallDataForm);
      ChkDsh.Parent := UninstallDataForm;
      ChkDsh.Top := ScaleY(164);
      ChkDsh.Left := ScaleX(24);
      ChkDsh.Width := ScaleX(452);
      ChkDsh.Caption := '干活数据（dsh：记忆/门禁插件/干活 Key）';
      ChkDsh.Checked := False;

      ChkLogs := TNewCheckBox.Create(UninstallDataForm);
      ChkLogs.Parent := UninstallDataForm;
      ChkLogs.Top := ScaleY(204);
      ChkLogs.Left := ScaleX(24);
      ChkLogs.Width := ScaleX(452);
      ChkLogs.Caption := '日志（logs）';
      ChkLogs.Checked := False;

      BtnAll := TNewButton.Create(UninstallDataForm);
      BtnAll.Parent := UninstallDataForm;
      BtnAll.Top := ScaleY(260);
      BtnAll.Left := ScaleX(24);
      BtnAll.Width := ScaleX(100);
      BtnAll.Height := ScaleY(28);
      BtnAll.Caption := '全选';
      BtnAll.OnClick := @UninstallSelectAllClick;

      BtnNone := TNewButton.Create(UninstallDataForm);
      BtnNone.Parent := UninstallDataForm;
      BtnNone.Top := ScaleY(260);
      BtnNone.Left := ScaleX(136);
      BtnNone.Width := ScaleX(100);
      BtnNone.Height := ScaleY(28);
      BtnNone.Caption := '全不选';
      BtnNone.OnClick := @UninstallSelectNoneClick;

      BtnOK := TNewButton.Create(UninstallDataForm);
      BtnOK.Parent := UninstallDataForm;
      BtnOK.Top := ScaleY(260);
      BtnOK.Left := ScaleX(384);
      BtnOK.Width := ScaleX(100);
      BtnOK.Height := ScaleY(28);
      BtnOK.Caption := '确定';
      BtnOK.ModalResult := mrOk;  // 点确定自动关窗，ShowModal 返回 mrOk
      BtnOK.Default := True;

      // 只有点「确定」才执行删除（确定按钮 ModalResult=mrOk）；点右上角 X 关窗
      // 返回 mrCancel = 取消 = 全部保留。
      if UninstallDataForm.ShowModal() = mrOk then
        DeleteSelectedUserData();
    finally
      UninstallDataForm.Free();
    end;
  end;
end;
