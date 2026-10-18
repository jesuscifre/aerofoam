; Inno Setup: crea instalador/salida/AeroFoam_Setup_X.Y.exe a partir de instalador/dist/AeroFoam
; Se usa desde herramientas/crear_instalador.bat (que pasa la versión con /DVersion=...)

#ifndef Version
  #define Version "1.1"
#endif

[Setup]
AppId={{316739F6-1942-4360-AE6F-215F2D905343}
AppName=AeroFoam
AppVersion={#Version}
AppVerName=AeroFoam {#Version}
AppPublisher=AeroFoam
DefaultDirName={autopf}\AeroFoam
DefaultGroupName=AeroFoam
DisableProgramGroupPage=yes
; instalación para el usuario actual, sin pedir permisos de administrador
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=salida
OutputBaseFilename=AeroFoam_Setup_{#Version}
SetupIconFile=aerofoam.ico
UninstallDisplayIcon={app}\AeroFoam.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; al actualizar se borra la versión anterior del programa (los datos del usuario no están aquí)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\AeroFoam\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AeroFoam"; Filename: "{app}\AeroFoam.exe"
Name: "{group}\Desinstalar AeroFoam"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AeroFoam"; Filename: "{app}\AeroFoam.exe"; Tasks: escritorio

[Run]
Filename: "{app}\AeroFoam.exe"; Description: "{cm:LaunchProgram,AeroFoam}"; Flags: nowait postinstall skipifsilent
