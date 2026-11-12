#define AppName "Phone-to-PC Audio"
#define AppVersion "1.0.0"
#define AppPublisher "Phone-to-PC Audio contributors"
#define AppExeName "PhoneToPcReceiver.exe"
#ifndef AppFilesDir
  #define AppFilesDir "dist\PhoneToPcReceiver"
#endif

[Setup]
AppId={{C2BC507F-7822-44CC-BDA9-8E8186AA57FC}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/shihab1712/PhoneToPCAudio
AppSupportURL=https://github.com/shihab1712/PhoneToPCAudio/issues
AppUpdatesURL=https://github.com/shihab1712/PhoneToPCAudio
DefaultDirName={localappdata}\Programs\Phone-to-PC Audio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
LicenseFile=..\LICENSE
OutputDir=dist\installer
OutputBaseFilename=PhoneToPcAudio-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppFilesDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent
