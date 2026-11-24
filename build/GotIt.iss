; Instalador do Got It! para Windows (Inno Setup 6.3+ ou 7). Gerado pelo build.ps1.

#define AppName "Got It!"
#define AppVersion "0.1.2"
#define AppExe "GotIt.exe"

[Setup]
AppId={{9C2B7E14-5A63-4F0D-8E2B-41C6D7A90F3E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Color Software
AppPublisherURL=https://colorsoftware.com.br
DefaultDirName={autopf}\Got It
DefaultGroupName=Got It!
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=GotIt_Setup_{#AppVersion}
SetupIconFile=..\assets\GotIt.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Sem pedir senha de administrador: instala para a pessoa (dá para escolher "para todos" no assistente).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador do {#AppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\GotIt\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; O AppUserModelID é o mesmo que o app declara ao abrir (main.py): a janela fica ligada ao atalho
; e a barra de tarefas mostra o ícone do Got It!.
Name: "{autoprograms}\Got It!"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; AppUserModelID: "ColorSoftware.GotIt"
Name: "{autodesktop}\Got It!"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; AppUserModelID: "ColorSoftware.GotIt"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o Got It!"; Flags: nowait postinstall skipifsilent
