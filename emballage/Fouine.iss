; Installateur Windows de Fouine (Inno Setup 6).
;
;   iscc /DVersion=0.4.0 emballage\Fouine.iss
;
; Il prend le dossier fabriqué par PyInstaller (dist\Fouine) et écrit
; Fouine-<version>-installation.exe à la racine du dépôt.
; Installation pour l'utilisateur seul : aucun droit d'administrateur n'est demandé.

#ifndef Version
  #error Donnez la version : iscc /DVersion=x.y.z emballage\Fouine.iss
#endif

[Setup]
; Identifiant de Fouine pour Windows : ne jamais le changer, il sert aux mises à jour.
AppId={{6B0F1C0E-6E0B-4B6C-9C1F-F0A1E5D2B7A4}
AppName=Fouine
AppVersion={#Version}
AppVerName=Fouine {#Version}
AppPublisher=RomainC-lab
AppPublisherURL=https://github.com/RomainC-lab/fouine
AppSupportURL=https://github.com/RomainC-lab/fouine
VersionInfoVersion={#Version}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Fouine
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SourceDir=..
OutputDir=.
OutputBaseFilename=Fouine-{#Version}-installation
SetupIconFile=emballage\fouine.ico
UninstallDisplayIcon={app}\Fouine.exe
UninstallDisplayName=Fouine
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Fouine tient ce nom tant qu'il tourne : l'installateur demande de le fermer d'abord.
AppMutex=Fouine.RomainC-lab.application
CloseApplications=no

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "bureau"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Mise à jour : l'ancien programme est retiré en entier avant de poser le nouveau.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Fouine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Fouine"; Filename: "{app}\Fouine.exe"; WorkingDir: "{app}"; Comment: "Retrouver ses fichiers par le sens, sans rien envoyer hors du PC"
Name: "{autodesktop}\Fouine"; Filename: "{app}\Fouine.exe"; WorkingDir: "{app}"; Comment: "Retrouver ses fichiers par le sens, sans rien envoyer hors du PC"; Tasks: bureau

[Run]
Filename: "{app}\Fouine.exe"; Description: "{cm:LaunchProgram,Fouine}"; Flags: nowait postinstall skipifsilent

[Code]
// À la désinstallation, l'index, les réglages et les modèles téléchargés sont gardés,
// sauf si la personne demande de les supprimer. Une désinstallation silencieuse ne
// pose pas la question et ne supprime donc rien.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Donnees: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Donnees := ExpandConstant('{localappdata}\Fouine');
    if DirExists(Donnees) and not UninstallSilent then
    begin
      if MsgBox('Fouine est désinstallé.' + #13#10 + #13#10 +
                'Voulez-vous aussi supprimer son index, ses réglages et les modèles téléchargés ?' + #13#10 +
                Donnees + #13#10 + #13#10 +
                'Vos propres fichiers ne sont pas concernés. Répondez « Non » si vous comptez réinstaller Fouine : ' +
                'vous éviterez de tout réindexer et de retélécharger les modèles.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Donnees, True, True, True);
    end;
  end;
end;
