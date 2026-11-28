#define AppName "PhoneToPC"
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppPublisher "PhoneToPC contributors"
#define AppExeName "PhoneToPC.exe"
#ifndef AppFilesDir
  #define AppFilesDir "dist\PhoneToPC"
#endif

[Setup]
AppId={{C2BC507F-7822-44CC-BDA9-8E8186AA57FC}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/shihab1712/PhoneToPC
AppSupportURL=https://github.com/shihab1712/PhoneToPC/issues
AppUpdatesURL=https://github.com/shihab1712/PhoneToPC
DefaultDirName={localappdata}\Programs\Phone-to-PC Audio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
LicenseFile=..\LICENSE
OutputDir=dist\installer
OutputBaseFilename=PhoneToPC-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#AppFilesDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\PhoneToPcReceiver.exe"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent
