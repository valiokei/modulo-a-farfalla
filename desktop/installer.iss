#ifndef BuildVersion
  #define BuildVersion "development"
#endif
[Setup]
AppId={{C2A8CD28-14A9-4ECB-988C-402B42F4D772}
AppName=Modulo a Farfalla
AppVersion={#BuildVersion}
AppPublisher=BrunaLab
DefaultDirName={localappdata}\Programs\ModuloAFarfalla
DefaultGroupName=Modulo a Farfalla
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist\installer
OutputBaseFilename=Modulo-a-Farfalla-Setup-{#BuildVersion}-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\ModuloAFarfalla.exe
CloseApplications=yes
RestartApplications=no
SetupMutex=ModuloAFarfallaSetup

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\ModuloAFarfalla\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\ModuloAFarfallaUpdater.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Modulo a Farfalla"; Filename: "{app}\ModuloAFarfalla.exe"
Name: "{autodesktop}\Modulo a Farfalla"; Filename: "{app}\ModuloAFarfalla.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ModuloAFarfalla.exe"; Description: "{cm:LaunchProgram,Modulo a Farfalla}"; Flags: nowait postinstall skipifsilent

; No UninstallDelete entries: database, originals and settings in LocalAppData are retained.
