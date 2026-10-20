#define MyAppName "FOOCUS"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "FOOCUS"
#define MyAppExeName "FocusFlow.exe"

[Setup]
AppId={{7EDB0D56-07B7-4C47-9EA6-4B4A6D331D65}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\FocusFlow
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist-installer
OutputBaseFilename=FOOCUS-Setup
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos adicionales:"; Flags: unchecked

[Files]
Source: "..\dist\FocusFlow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\FOOCUS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\FOOCUS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Preparando el componente web de FOOCUS..."; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar FOOCUS"; Flags: postinstall nowait skipifsilent
