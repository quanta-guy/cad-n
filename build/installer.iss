; Inno Setup script for CAD-N (doc 15.1 Stage 4).
; Build the one-folder app first:  pyinstaller build/cad_n.spec --noconfirm
; Then compile this script with Inno Setup 6 (ISCC.exe build\installer.iss).

#define MyAppName "CAD-N"
#define MyAppVersion "0.4.0"
#define MyAppPublisher "CAD-N"
#define MyAppExeName "CAD-N.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\CAD-N
DefaultGroupName=CAD-N
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=CAD-N_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\cad_n\resources\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The PyInstaller one-folder output:
Source: "..\dist\CAD-N\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\USER_GUIDE.md"; DestDir: "{app}"; Flags: isreadme
Source: "..\CHANGELOG.md"; DestDir: "{app}"

[Icons]
Name: "{group}\CAD-N"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall CAD-N"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CAD-N"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch CAD-N"; Flags: nowait postinstall skipifsilent
