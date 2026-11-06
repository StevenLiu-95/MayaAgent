; Maya Agent — Windows commercial installer (Inno Setup 6)
; Build: installer\build.bat  (requires ISCC + optional vendor_cache)
;
; No system Python required on the end-user machine: post-install runs mayapy.

#define MyAppName "Maya Agent"
#define MyAppVersion "1.6.0"
#define MyAppPublisher "MayaAgent"
#define MyAppURL "https://github.com/"
#define MyAppExeName "install.bat"
#define ProjRoot ".."

[Setup]
AppId={{A7E3C2B1-9F40-4D6E-8C1A-5B6D7E8F9A0B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\MayaAgent
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=..\dist
OutputBaseFilename=MayaAgent-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
InfoAfterFile=FINISH.txt
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut to the install folder"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Application tree
Source: "{#ProjRoot}\maya_agent\*"; DestDir: "{app}\maya_agent"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjRoot}\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjRoot}\resources\*"; DestDir: "{app}\resources"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjRoot}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjRoot}\rules\*"; DestDir: "{app}\rules"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjRoot}\VERSION"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\requirements-mcp.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\install.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\install_dragdrop.mel"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjRoot}\recover_tools_dragdrop.mel"; DestDir: "{app}"; Flags: ignoreversion
; Offline deps (built by scripts\build_vendor_cache.py) — optional at compile time
Source: "{#ProjRoot}\vendor_cache\*"; DestDir: "{app}\vendor_cache"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
; Installer helpers
Source: "run_engine.bat"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "FINISH.txt"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName} Folder"; Filename: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}"; Tasks: desktopicon

[Code]
var
  VersionPage: TWizardPage;
  Cb2020, Cb2022, Cb2023, Cb2024, Cb2025, Cb2026: TNewCheckBox;
  VersionsFile: string;

function MayaLikelyInstalled(const Ver: string): Boolean;
var
  DocsMaya, PrefsPath, InstallPath: string;
begin
  Result := False;
  DocsMaya := ExpandConstant('{userdocs}') + '\maya\' + Ver;
  if DirExists(DocsMaya) then
  begin
    Result := True;
    Exit;
  end;
  PrefsPath := ExpandConstant('{userdocs}') + '\maya\' + Ver + '\prefs';
  if DirExists(PrefsPath) then
  begin
    Result := True;
    Exit;
  end;
  if RegQueryStringValue(HKLM64,
       'SOFTWARE\Autodesk\Maya\' + Ver + '\Setup\InstallPath',
       'MAYA_INSTALL_LOCATION', InstallPath) then
  begin
    if DirExists(InstallPath) then
      Result := True;
  end;
end;

procedure CreateVersionPage;
begin
  VersionPage := CreateCustomPage(wpSelectDir,
    'Maya versions',
    'Select which Maya versions should load Maya Agent (detected versions are checked).');

  Cb2020 := TNewCheckBox.Create(VersionPage);
  Cb2020.Parent := VersionPage.Surface;
  Cb2020.Caption := 'Maya 2020';
  Cb2020.Top := ScaleY(8);
  Cb2020.Left := ScaleX(8);
  Cb2020.Width := ScaleX(300);
  Cb2020.Checked := MayaLikelyInstalled('2020');

  Cb2022 := TNewCheckBox.Create(VersionPage);
  Cb2022.Parent := VersionPage.Surface;
  Cb2022.Caption := 'Maya 2022';
  Cb2022.Top := Cb2020.Top + ScaleY(28);
  Cb2022.Left := ScaleX(8);
  Cb2022.Width := ScaleX(300);
  Cb2022.Checked := MayaLikelyInstalled('2022');

  Cb2023 := TNewCheckBox.Create(VersionPage);
  Cb2023.Parent := VersionPage.Surface;
  Cb2023.Caption := 'Maya 2023';
  Cb2023.Top := Cb2022.Top + ScaleY(28);
  Cb2023.Left := ScaleX(8);
  Cb2023.Width := ScaleX(300);
  Cb2023.Checked := MayaLikelyInstalled('2023');

  Cb2024 := TNewCheckBox.Create(VersionPage);
  Cb2024.Parent := VersionPage.Surface;
  Cb2024.Caption := 'Maya 2024';
  Cb2024.Top := Cb2023.Top + ScaleY(28);
  Cb2024.Left := ScaleX(8);
  Cb2024.Width := ScaleX(300);
  Cb2024.Checked := MayaLikelyInstalled('2024');

  Cb2025 := TNewCheckBox.Create(VersionPage);
  Cb2025.Parent := VersionPage.Surface;
  Cb2025.Caption := 'Maya 2025';
  Cb2025.Top := Cb2024.Top + ScaleY(28);
  Cb2025.Left := ScaleX(8);
  Cb2025.Width := ScaleX(300);
  Cb2025.Checked := MayaLikelyInstalled('2025');

  Cb2026 := TNewCheckBox.Create(VersionPage);
  Cb2026.Parent := VersionPage.Surface;
  Cb2026.Caption := 'Maya 2026';
  Cb2026.Top := Cb2025.Top + ScaleY(28);
  Cb2026.Left := ScaleX(8);
  Cb2026.Width := ScaleX(300);
  Cb2026.Checked := MayaLikelyInstalled('2026');
end;

function SelectedVersions: string;
begin
  Result := '';
  if Cb2020.Checked then Result := Result + '2020 ';
  if Cb2022.Checked then Result := Result + '2022 ';
  if Cb2023.Checked then Result := Result + '2023 ';
  if Cb2024.Checked then Result := Result + '2024 ';
  if Cb2025.Checked then Result := Result + '2025 ';
  if Cb2026.Checked then Result := Result + '2026 ';
  Result := Trim(Result);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Sel: string;
begin
  Result := True;
  if CurPageID = VersionPage.ID then
  begin
    Sel := SelectedVersions;
    if Sel = '' then
    begin
      MsgBox('Please select at least one Maya version.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure WriteVersionsFile(const Path, Versions: string);
var
  S: string;
begin
  { One version per line — install_engine parses whitespace/newlines }
  S := Versions;
  StringChange(S, ' ', #13#10);
  SaveStringToFile(Path, S + #13#10, False);
end;

function RunEngine(const ExtraArgs: string): Boolean;
var
  ResultCode: Integer;
  Cmd, LogFile, VerFile, CacheArg: string;
begin
  VerFile := ExpandConstant('{app}\unins_versions.txt');
  LogFile := ExpandConstant('{app}\install_engine.log');
  WriteVersionsFile(VerFile, SelectedVersions);

  CacheArg := '';
  if DirExists(ExpandConstant('{app}\vendor_cache')) then
    CacheArg := ' --vendor-cache "' + ExpandConstant('{app}\vendor_cache') + '"';

  Cmd := '"' + ExpandConstant('{app}\installer\run_engine.bat') + '"' +
         ' --versions-from-file "' + VerFile + '"' +
         ' --log-file "' + LogFile + '"' +
         CacheArg + ' ' + ExtraArgs;

  Log('Running: ' + Cmd);
  Result := Exec(
    ExpandConstant('{cmd}'),
    '/C ' + Cmd,
    ExpandConstant('{app}'),
    SW_SHOW,
    ewWaitUntilTerminated,
    ResultCode
  );
  if not Result then
  begin
    MsgBox('Failed to launch install engine.', mbError, MB_OK);
    Exit;
  end;
  if ResultCode <> 0 then
  begin
    MsgBox(
      'Install engine finished with code ' + IntToStr(ResultCode) + '.' + #13#10 +
      'Hooks may still be partial. See:' + #13#10 + LogFile + #13#10 +
      'You can also drag install_dragdrop.mel into Maya.',
      mbInformation,
      MB_OK
    );
  end;
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Configuring Maya hooks and dependencies…';
    RunEngine('');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  VerFile, Cmd: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    VerFile := ExpandConstant('{app}\unins_versions.txt');
    Cmd := '"' + ExpandConstant('{app}\installer\run_engine.bat') + '" --uninstall';
    if FileExists(VerFile) then
      Cmd := Cmd + ' --versions-from-file "' + VerFile + '"';
    Exec(
      ExpandConstant('{cmd}'),
      '/C ' + Cmd,
      ExpandConstant('{app}'),
      SW_SHOW,
      ewWaitUntilTerminated,
      ResultCode
    );
  end;
end;

procedure InitializeWizard;
begin
  CreateVersionPage;
end;
