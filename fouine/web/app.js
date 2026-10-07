"use strict";
// Interface de Fouine. Tout texte venu des fichiers est posé avec textContent,
// jamais interprété comme du HTML.

// -------------------------------------------------------------------- thème
// Le thème choisi avec le bouton est retenu par Fouine, pas par le navigateur : la page arrive
// avec « data-theme » déjà posé sur <html>. Sans choix, elle suit le réglage du PC.

const racine = document.documentElement;
const prefereSombre = window.matchMedia("(prefers-color-scheme: dark)");

function themeActuel() {
  return racine.dataset.theme || (prefereSombre.matches ? "dark" : "light");
}

// ------------------------------------------------------------------- outils

const $ = (id) => document.getElementById(id);
const jeton = location.hash.slice(1);
let reglages = null;
let suivi = null;
let dossierCourant = null;
let dernierEtat = null;

function el(balise, proprietes, ...enfants) {
  const noeud = document.createElement(balise);
  for (const [cle, valeur] of Object.entries(proprietes || {})) {
    if (cle === "classe") noeud.className = valeur;
    else if (cle === "clic") noeud.addEventListener("click", valeur);
    else noeud.setAttribute(cle, valeur);
  }
  for (const enfant of enfants) noeud.append(enfant);
  return noeud;
}

function modele(id) {
  return $(id).content.firstElementChild.cloneNode(true);
}

function ico(nom, classe) {
  const dessin = modele("t-ico");
  dessin.querySelector("use").setAttribute("href", "#i-" + nom);
  if (classe) dessin.classList.add(...classe.split(" "));
  return dessin;
}

function nombre(n) { return n.toLocaleString("fr-FR"); }
function pluriel(n, mot) { return nombre(n) + " " + mot + (n > 1 ? "s" : ""); }
function taille(octets) {
  if (octets < 1024 * 1024) return Math.max(1, Math.round(octets / 1024)) + " Ko";
  return (octets / 1024 / 1024).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " Mo";
}

// Familles de fichiers : une couleur et une pastille par famille.
const FAMILLES = {
  pdf: "pdf",
  docx: "texte", doc: "texte", odt: "texte", rtf: "texte",
  xlsx: "tableur", xls: "tableur", ods: "tableur", csv: "tableur", tsv: "tableur",
  pptx: "diapo", ppt: "diapo", odp: "diapo",
  html: "web", htm: "web",
  jpg: "image", jpeg: "image", jfif: "image", png: "image", webp: "image", bmp: "image", gif: "image",
  tif: "image", tiff: "image",
};
function extension(nom) {
  const point = nom.lastIndexOf(".");
  return point > 0 ? nom.slice(point + 1).toLowerCase() : "";
}
function famille(ext) { return FAMILLES[ext.replace(/^\./, "")] || "note"; }

function alerter(message) {
  $("texte-alerte").textContent = message || "";
  $("alerte").hidden = !message;
}

async function appeler(action, corps) {
  let reponse;
  try {
    reponse = await fetch("/api/" + action, {
      method: corps === undefined ? "GET" : "POST",
      headers: { "X-Fouine-Jeton": jeton, "Content-Type": "application/json" },
      body: corps === undefined ? undefined : JSON.stringify(corps),
    });
  } catch (erreur) {
    throw new Error("Fouine ne répond plus. Relancez-le, puis utilisez la nouvelle page qui s'ouvre.");
  }
  const donnees = await reponse.json().catch(() => ({}));
  if (!reponse.ok) throw new Error(donnees.erreur || "Une erreur est survenue.");
  return donnees;
}

async function essayer(travail) {
  try {
    alerter("");
    return await travail();
  } catch (erreur) {
    alerter(erreur.message);
    return null;
  }
}

function afficherTheme() {
  const sombre = themeActuel() === "dark";
  $("theme").setAttribute("aria-label", sombre ? "Passer au thème clair" : "Passer au thème sombre");
}

function changerTheme() {
  const nouveau = themeActuel() === "dark" ? "light" : "dark";
  racine.dataset.theme = nouveau;
  afficherTheme();
  // Si Fouine ne peut pas le retenir, le choix vaut au moins pour cette fois.
  appeler("theme", { theme: nouveau }).catch(() => {});
}

// ------------------------------------------------------------------ onglets

function montrer(onglet) {
  for (const bouton of document.querySelectorAll(".onglet")) {
    if (bouton.dataset.onglet === onglet) bouton.setAttribute("aria-current", "page");
    else bouton.removeAttribute("aria-current");
  }
  $("chercher").hidden = onglet !== "chercher";
  $("regler").hidden = onglet !== "regler";
  if (onglet === "chercher" && !$("zone-recherche").hidden) $("question").focus();
}

// ---------------------------------------------------------------- recherche

function surligner(texte, mots) {
  // Met en valeur les mots de la question, sans tenir compte des accents ni des majuscules.
  const morceau = document.createDocumentFragment();
  const sansAccent = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const cibles = mots.map(sansAccent).filter((m) => m.length > 2);
  let reste = 0;
  const mot = /[\p{L}\p{N}]+/gu;
  let trouve;
  while ((trouve = mot.exec(texte)) !== null) {
    const simple = sansAccent(trouve[0]);
    if (!cibles.some((c) => simple.startsWith(c))) continue;
    morceau.append(texte.slice(reste, trouve.index), el("mark", {}, trouve[0]));
    reste = trouve.index + trouve[0].length;
  }
  morceau.append(texte.slice(reste));
  return morceau;
}

function pastille(nom) {
  const ext = extension(nom);
  return el("span", { classe: "type type-" + famille(ext), "aria-hidden": "true" }, ext.slice(0, 4) || "?");
}

function titre(nom) {
  const ext = extension(nom);
  if (!ext) return el("h3", {}, nom);
  return el("h3", {}, nom.slice(0, -ext.length - 1), el("span", { classe: "ext" }, "." + ext));
}

// Deux blocs séparés, « Documents » puis « Images » : chacun a son modèle, et leurs notes
// ne se comparent pas. Le bloc Images n'existe que si des images sont dans l'index.
function afficherResultats(question, resultats, avecImages) {
  const zone = $("bloc-documents");
  zone.replaceChildren();
  if (avecImages) zone.append(el("h3", { classe: "titre-bloc" }, ico("page"), "Documents"));
  if (!resultats.length && avecImages) {
    zone.append(el("p", { classe: "discret aucun-document" },
      "Aucun document ne correspond. Regardez les images ci-dessous, ou essayez d'autres mots."));
    return;
  }
  if (!resultats.length) {
    zone.append(
      el("div", { classe: "bredouille" },
        modele("t-bredouille"),
        el("div", {},
          el("h3", {}, "Rien trouvé pour « " + question + " »."),
          el("ul", {},
            el("li", {}, "Essayez d'autres mots, ou décrivez le contenu autrement."),
            el("li", {}, "Si le fichier est récent, relancez l'indexation dans « Dossiers et filtres ».")))));
    return;
  }
  const mots = question.split(/\s+/).filter(Boolean);
  zone.append(el("p", { classe: "compte" },
    resultats.length > 1 ? nombre(resultats.length) + " fichiers trouvés" : "1 fichier trouvé"));
  for (const r of resultats) {
    const ouvrir = (quoi) => () => essayer(() => appeler("ouvrir", { id: r.id, quoi }));
    zone.append(
      el("article", { classe: "resultat" },
        pastille(r.nom),
        el("div", { classe: "resultat-tete" },
          titre(r.nom),
          el("span", { classe: "date" }, "Modifié le " + r.modifie)),
        el("p", { classe: "extrait" }, surligner(r.extrait, mots)),
        el("p", { classe: "ou" }, ico("dossier"), el("span", { classe: "chemin" }, r.dossier)),
        el("p", { classe: "actions" },
          el("button", { type: "button", classe: "petit", clic: ouvrir("fichier") }, ico("sortir"), "Ouvrir le fichier"),
          el("button", { type: "button", classe: "petit", clic: ouvrir("dossier") }, ico("dossier"), "Ouvrir le dossier"))));
  }
}

// Les vignettes sont demandées avec le jeton, comme le reste, puis posées dans la page
// depuis la mémoire du navigateur (adresse « blob: »). Elles sont libérées à chaque recherche.
let vignettes = [];

function oublierVignettes() {
  for (const adresse of vignettes) URL.revokeObjectURL(adresse);
  vignettes = [];
}

async function poserVignette(cadre, identifiant) {
  try {
    const reponse = await fetch("/api/vignette?id=" + identifiant, { headers: { "X-Fouine-Jeton": jeton } });
    if (!reponse.ok) throw new Error("vignette refusée");
    const adresse = URL.createObjectURL(await reponse.blob());
    vignettes.push(adresse);
    const dessin = el("img", { alt: "", loading: "lazy" });
    dessin.addEventListener("load", () => cadre.classList.add("prete"));
    dessin.src = adresse;
    cadre.replaceChildren(dessin);
  } catch (erreur) {
    cadre.classList.add("sans-vignette");
    cadre.replaceChildren(ico("image"));
  }
}

function afficherImages(images) {
  const zone = $("bloc-images");
  zone.replaceChildren();
  if (!images.length) return;
  zone.append(
    el("h3", { classe: "titre-bloc" }, ico("image"), "Images"),
    el("p", { classe: "discret note-images" },
      images.length > 1
        ? "Les " + nombre(images.length) + " images les plus proches de votre recherche, la plus proche en premier. Les dernières peuvent n'avoir aucun rapport."
        : "La seule image de l'index. Elle peut n'avoir aucun rapport avec votre recherche."));
  const planche = el("ul", { classe: "planche" });
  for (const image of images) {
    const ouvrir = (quoi) => () => essayer(() => appeler("ouvrir", { id: image.id, quoi }));
    const cadre = el("button", { type: "button", classe: "cadre", title: "Ouvrir " + image.nom,
      "aria-label": "Ouvrir l'image " + image.nom, clic: ouvrir("fichier") });
    poserVignette(cadre, image.id);
    planche.append(
      el("li", { classe: "vue" },
        cadre,
        el("div", { classe: "legende-vue" },
          titre(image.nom),
          el("p", { classe: "ou" }, ico("dossier"), el("span", { classe: "chemin" }, image.dossier)),
          el("p", { classe: "date" }, "Modifiée le " + image.modifie),
          el("p", { classe: "actions" },
            el("button", { type: "button", classe: "petit", clic: ouvrir("fichier"), "aria-label": "Ouvrir le fichier " + image.nom },
              ico("sortir"), "Ouvrir"),
            el("button", { type: "button", classe: "petit", clic: ouvrir("dossier"), "aria-label": "Ouvrir le dossier de " + image.nom },
              ico("dossier"), "Dossier")))));
  }
  zone.append(planche);
}

function afficherAttente(avecImages) {
  const fantome = () => el("div", { classe: "fantome", "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"));
  $("bloc-documents").replaceChildren(el("p", { classe: "attente" }, "Fouine cherche…"), fantome(), fantome(), fantome());
  $("bloc-images").replaceChildren();
  if (avecImages) $("bloc-images").append(el("p", { classe: "attente" }, "Fouine regarde aussi dans vos images…"));
}

let recherche = 0;

async function chercher(evenement) {
  evenement.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  const numero = ++recherche; // une recherche plus récente remplace celle-ci
  const avecImages = Boolean(dernierEtat && dernierEtat.index.images);
  $("form-recherche").classList.add("flaire");
  oublierVignettes();
  afficherAttente(avecImages);
  // Les documents s'affichent dès qu'ils sont trouvés ; les images suivent (leur modèle est plus lent).
  const images = avecImages ? essayer(() => appeler("recherche_images", { question })) : Promise.resolve(null);
  const reponse = await essayer(() => appeler("recherche", { question }));
  if (numero !== recherche) return;
  if (reponse) afficherResultats(question, reponse.resultats, avecImages);
  else $("bloc-documents").replaceChildren();
  const trouvees = await images;
  if (numero !== recherche) return;
  $("form-recherche").classList.remove("flaire");
  if (trouvees) afficherImages(trouvees.images);
  else $("bloc-images").replaceChildren();
}

function viderResultats() {
  recherche += 1;
  oublierVignettes();
  $("bloc-documents").replaceChildren();
  $("bloc-images").replaceChildren();
}

function afficherEtatIndex(etat) {
  const index = etat.index;
  const vide = !index.fichiers;
  $("accueil").hidden = !vide;
  $("zone-recherche").hidden = vide;
  if (vide) {
    viderResultats();
    const lecture = etat.tache.en_cours;
    $("accueil-titre").textContent = lecture
      ? "Fouine lit vos fichiers pour la première fois."
      : "Fouine ne connaît encore aucun de vos fichiers.";
    $("accueil-suite").textContent = lecture
      ? "Vous pourrez chercher dès que les premiers fichiers seront lus. La progression s'affiche dans « Dossiers et filtres »."
      : "Montrez-lui les dossiers qu'il a le droit de lire. Il les parcourt une fois, puis vous retrouvez un document en décrivant ce qu'il contient.";
    $("marche").hidden = lecture;
    $("accueil-bouton").textContent = lecture ? "Voir la progression" : "Choisir mes dossiers";
    return;
  }
  $("amorce-suite").textContent = index.images
    ? "Décrivez ce que contient le fichier, ou ce qu'on voit sur l'image, avec vos mots."
    : "Décrivez ce que contient le fichier, avec vos mots.";
  let texte = pluriel(index.fichiers, "fichier") + " dans l'index";
  if (index.images) texte += " (dont " + pluriel(index.images, "image") + ")";
  if (index.derniere_indexation) texte += ", mis à jour le " + index.derniere_indexation;
  texte += etat.tache.en_cours ? ". Indexation en cours." : ".";
  $("etat-index").textContent = texte;
}

// ----------------------------------------------------------------- réglages

function afficherReglages(etat) {
  reglages = etat.reglages;
  const liste = $("liste-dossiers");
  liste.replaceChildren();
  if (!reglages.dossiers.length) {
    liste.append(el("li", { classe: "aucun" }, "Aucun dossier pour l'instant. Ajoutez-en un ci-dessous."));
  }
  for (const dossier of reglages.dossiers) {
    liste.append(
      el("li", {},
        ico("dossier"),
        el("span", { classe: "chemin" }, dossier),
        el("button", { type: "button", classe: "petit", "aria-label": "Retirer " + dossier,
          clic: () => changerDossiers(reglages.dossiers.filter((d) => d !== dossier)) }, ico("croix"), "Retirer")));
  }
  const propositions = $("propositions");
  propositions.replaceChildren();
  for (const dossier of etat.dossiers_proposes.filter((d) => !reglages.dossiers.includes(d))) {
    const nom = dossier.split(/[\\/]/).filter(Boolean).pop();
    propositions.append(
      el("button", { type: "button", classe: "petit", title: dossier, "aria-label": "Ajouter le dossier " + nom,
        clic: () => changerDossiers(reglages.dossiers.concat([dossier])) }, ico("plus"), nom));
  }
  $("extensions").value = reglages.extensions.join(" ");
  $("taille").value = reglages.taille_max_mo;
  $("exclus").value = reglages.dossiers_exclus.join("\n");
  $("caches").checked = reglages.inclure_caches;
  $("lire-images").checked = reglages.lire_images;
  $("reglages-images").hidden = !reglages.lire_images;
  $("image-cote").value = reglages.image_cote_min_px;
  $("image-taille").value = reglages.image_taille_max_mo;
  $("taille-modele-images").textContent = etat.taille_modele_images;
  $("sensibles").replaceChildren(...reglages.motifs_sensibles.map((m) => el("span", {}, m)));
  $("fichier-reglages").textContent = etat.fichier_reglages;
  $("version").textContent = etat.version;
}

function lireFormulaire() {
  return {
    dossiers: reglages.dossiers,
    extensions: $("extensions").value.split(/[\s,;]+/).filter(Boolean),
    taille_max_mo: Number($("taille").value),
    dossiers_exclus: $("exclus").value.split("\n").map((l) => l.trim()).filter(Boolean),
    inclure_caches: $("caches").checked,
    lire_images: $("lire-images").checked,
    image_cote_min_px: Number($("image-cote").value),
    image_taille_max_mo: Number($("image-taille").value),
  };
}

async function enregistrer(nouveaux) {
  const reponse = await essayer(() => appeler("enregistrer", { reglages: nouveaux }));
  if (!reponse) return false;
  $("apercu").replaceChildren();
  await rafraichir(true);
  $("enregistre").textContent = "Réglages enregistrés.";
  setTimeout(() => { $("enregistre").textContent = ""; }, 2500);
  return true;
}

function changerDossiers(dossiers) {
  return enregistrer(Object.assign(lireFormulaire(), { dossiers }));
}

// --------------------------------------------------------- choix d'un dossier

async function allerDans(chemin) {
  const reponse = await essayer(() => appeler("dossiers", { chemin }));
  if (!reponse) return;
  dossierCourant = reponse.chemin;
  $("dossier-courant").textContent = reponse.chemin || "Ce PC";
  $("choisir").disabled = !reponse.chemin;
  const liste = $("sous-dossiers");
  liste.replaceChildren();
  if (reponse.parent !== null) {
    liste.append(el("li", {}, el("button", { type: "button", clic: () => allerDans(reponse.parent) },
      ico("monter"), "Remonter d'un niveau")));
  }
  for (const sous of reponse.sous_dossiers) {
    liste.append(el("li", {}, el("button", { type: "button", clic: () => allerDans(sous.chemin) },
      ico("dossier"), sous.nom, ico("chevron", "fin"))));
  }
  if (!reponse.sous_dossiers.length) {
    liste.append(el("li", { classe: "vide" }, "Pas de sous-dossier ici."));
  }
}

// ------------------------------------------------------ aperçu et indexation

function listeChemins(chemins) {
  return el("ul", { classe: "liste-chemins" }, ...chemins.map((c) => el("li", { classe: "chemin" }, c)));
}

function repartition(parType) {
  // Une bande colorée : la part de chaque type parmi les fichiers qui seraient lus.
  const types = Object.entries(parType).sort((x, y) => y[1] - x[1]);
  const bande = el("div", { classe: "bande", "aria-hidden": "true" });
  const legende = el("ul", { classe: "legende" });
  for (const [ext, n] of types) {
    const couleur = "var(--t-" + famille(ext) + ")";
    const part = el("i");
    part.style.flexGrow = String(n);
    part.style.setProperty("--c", couleur);
    bande.append(part);
    const ligne = el("li", {}, el("b", {}, nombre(n)), ext);
    ligne.style.setProperty("--c", couleur);
    legende.append(ligne);
  }
  return el("div", { classe: "repartition" }, bande, legende);
}

function duree(secondes) {
  if (secondes < 90) return "environ une minute";
  if (secondes < 3600 * 1.5) return "environ " + Math.round(secondes / 60) + " minutes";
  return "environ " + (secondes / 3600).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " heures";
}

function phraseImages(a) {
  // Ce sont les images qui prennent du temps : on dit combien il en reste, et pour combien
  // de temps si la vitesse de ce PC a déjà été mesurée. Sinon, aucune durée n'est promise.
  const n = a.acceptes.images;
  const reste = a.acceptes.images_a_lire;
  let texte = "Dont " + pluriel(n, "image") + ". ";
  if (!reste) return texte + "Toutes sont déjà lues : elles ne le seront pas de nouveau.";
  texte += reste === n ? "" : pluriel(reste, "image") + (reste > 1 ? " restent à lire. " : " reste à lire. ");
  if (a.duree_images_s !== null) return texte + "Lecture des images : " + duree(a.duree_images_s) + " sur ce PC.";
  return texte + "Comptez quelques secondes par image. Fouine mesure la vitesse de ce PC sur les premières images, "
    + "puis affiche le temps restant pendant l'indexation.";
}

function afficherApercu(a) {
  const zone = $("apercu");
  zone.replaceChildren();
  const ecartes = a.ecartes.reduce((s, g) => s + g.fichiers + g.dossiers, 0);
  zone.append(
    el("div", { classe: "chiffres" },
      el("div", { classe: "chiffre lus" }, el("strong", {}, nombre(a.acceptes.nombre)),
        el("span", {}, (a.acceptes.nombre > 1 ? "fichiers seraient lus" : "fichier serait lu") + " (" + taille(a.acceptes.taille) + ")")),
      el("div", { classe: "chiffre" }, el("strong", {}, nombre(ecartes)),
        el("span", {}, ecartes > 1 ? "fichiers ou dossiers laissés de côté" : "fichier ou dossier laissé de côté"))));
  if (Object.keys(a.acceptes.par_type).length) zone.append(repartition(a.acceptes.par_type));
  if (a.acceptes.images) zone.append(el("p", { classe: "apercu-images" }, ico("image"), el("span", {}, phraseImages(a))));
  for (const absent of a.introuvables) {
    zone.append(el("p", { classe: "alerte" }, ico("alerte"), el("span", {}, "Dossier introuvable en ce moment : " + absent)));
  }
  if (a.acceptes.exemples.length) {
    zone.append(el("details", {}, el("summary", {}, "Exemples de fichiers lus"), listeChemins(a.acceptes.exemples)));
  }
  if (!a.ecartes.length) return;
  const raisons = el("ul", { classe: "raisons" });
  for (const g of a.ecartes) {
    const combien = [g.fichiers ? pluriel(g.fichiers, "fichier") : "", g.dossiers ? pluriel(g.dossiers, "dossier") : ""]
      .filter(Boolean).join(", ");
    raisons.append(el("li", { classe: "raison" },
      el("div", {}, el("h4", {}, g.raison), el("p", { classe: "combien" }, combien)),
      listeChemins(g.exemples)));
  }
  zone.append(
    el("h3", { classe: "raisons-titre" }, "Laissé de côté, raison par raison"),
    raisons,
    el("p", { classe: "aide" }, "Un dossier laissé de côté n'est pas ouvert : il compte pour un, quel que soit son contenu."));
}

function phraseBilan(b) {
  const lus = b.nouveaux + b.modifies;
  const morceaux = [
    pluriel(lus, "fichier") + (lus > 1 ? " lus" : " lu") + (b.images ? " (dont " + pluriel(b.images, "image") + ")" : ""),
    b.inchanges + (b.inchanges > 1 ? " inchangés (non relus)" : " inchangé (non relu)"),
  ];
  if (b.retires) morceaux.push(b.retires + (b.retires > 1 ? " retirés de l'index" : " retiré de l'index"));
  if (b.illisibles) morceaux.push(b.illisibles + (b.illisibles > 1 ? " illisibles" : " illisible"));
  return (b.arrete ? "Indexation arrêtée avant la fin : " : "Indexation terminée : ") + morceaux.join(", ") + "."
    + (b.arrete ? " Relancez-la pour continuer là où elle s'est arrêtée." : "");
}

async function afficherIllisibles(etat) {
  const zone = $("illisibles");
  if (!etat.index.illisibles) { zone.replaceChildren(); return; }
  if (zone.dataset.nombre === String(etat.index.illisibles) && zone.firstChild) return;
  const reponse = await essayer(() => appeler("illisibles", {}));
  if (!reponse) return;
  zone.dataset.nombre = String(etat.index.illisibles);
  zone.replaceChildren(el("details", {},
    el("summary", {}, pluriel(etat.index.illisibles, "fichier")
      + (etat.index.illisibles > 1 ? " n'ont pas pu être lus" : " n'a pas pu être lu")),
    el("ul", { classe: "liste-chemins" },
      ...reponse.illisibles.map((i) => el("li", {}, el("span", { classe: "chemin" }, i.chemin), " : " + i.erreur)))));
}

function afficherTache(etat) {
  const t = etat.tache;
  $("indexer").disabled = t.en_cours;
  $("voir-apercu").disabled = t.en_cours;
  $("defaut").disabled = t.en_cours;
  $("arreter").hidden = !t.en_cours;
  $("progression").hidden = !t.en_cours;
  if (t.en_cours) {
    const barre = $("barre");
    let titreEtape;
    let texte;
    let pourcent = "";
    if (t.etape === "modele") {
      barre.removeAttribute("value");
      titreEtape = "Préparation du modèle";
      texte = "La toute première fois, il est téléchargé (" + etat.taille_modele + ") : cela peut prendre quelques minutes.";
    } else if (t.etape === "modele_images") {
      barre.removeAttribute("value");
      titreEtape = "Préparation du modèle des images";
      texte = "La toute première fois, il est téléchargé (" + etat.taille_modele_images + ") : cela peut prendre quelques minutes.";
    } else if (t.etape === "lecture" && t.total) {
      const part = Math.round((t.fait / t.total) * 100);
      barre.value = part;
      pourcent = part + " %";
      titreEtape = "Lecture du fichier " + nombre(Math.min(t.fait + 1, t.total)) + " sur " + nombre(t.total);
      if (t.reste_s) titreEtape += ", encore " + duree(t.reste_s);
      texte = t.fichier;
    } else {
      barre.removeAttribute("value");
      titreEtape = "Recherche des fichiers nouveaux ou modifiés…";
      texte = "";
    }
    $("titre-progression").textContent = titreEtape;
    $("pourcent").textContent = pourcent;
    $("texte-progression").textContent = texte;
    $("texte-progression").classList.toggle("chemin", t.etape === "lecture");
    $("bilan").hidden = true;
  } else if (t.erreur || t.bilan) {
    $("bilan").hidden = false;
    $("bilan").classList.toggle("erreur", Boolean(t.erreur));
    $("texte-bilan").textContent = t.erreur ? "L'indexation s'est arrêtée sur une erreur : " + t.erreur : phraseBilan(t.bilan);
  }
  if (t.en_cours && !suivi) suivi = setInterval(() => rafraichir(false), 1000);
  if (!t.en_cours && suivi) { clearInterval(suivi); suivi = null; }
}

async function rafraichir(avecReglages) {
  const etat = await essayer(() => appeler("etat"));
  if (!etat) {
    if (suivi) { clearInterval(suivi); suivi = null; }
    return null;
  }
  const finie = dernierEtat && dernierEtat.tache.en_cours && !etat.tache.en_cours;
  dernierEtat = etat;
  if (avecReglages || finie) afficherReglages(etat);
  afficherEtatIndex(etat);
  afficherTache(etat);
  if (!etat.tache.en_cours) await afficherIllisibles(etat);
  return etat;
}

// ------------------------------------------------------------------- départ

function brancher() {
  for (const bouton of document.querySelectorAll(".onglet")) {
    bouton.addEventListener("click", () => montrer(bouton.dataset.onglet));
  }
  $("theme").addEventListener("click", changerTheme);
  prefereSombre.addEventListener("change", afficherTheme);
  afficherTheme();
  $("aller-regler").addEventListener("click", () => montrer("regler"));
  $("form-recherche").addEventListener("submit", chercher);
  for (const id of ["extensions", "taille", "exclus", "caches", "lire-images", "image-cote", "image-taille"]) {
    $(id).addEventListener("change", () => enregistrer(lireFormulaire()));
  }
  $("defaut").addEventListener("click", () => enregistrer({ defaut: true }));
  $("ajouter-dossier").addEventListener("click", async () => {
    await allerDans(null);
    $("choix-dossier").showModal();
  });
  $("annuler").addEventListener("click", () => $("choix-dossier").close());
  $("choisir").addEventListener("click", async () => {
    $("choix-dossier").close();
    if (dossierCourant && !reglages.dossiers.includes(dossierCourant)) {
      await changerDossiers(reglages.dossiers.concat([dossierCourant]));
    }
  });
  $("voir-apercu").addEventListener("click", async () => {
    $("apercu").replaceChildren(el("p", { classe: "discret" }, "Comptage en cours…"));
    const reponse = await essayer(() => appeler("apercu", {}));
    if (reponse) afficherApercu(reponse);
    else $("apercu").replaceChildren();
  });
  $("indexer").addEventListener("click", async () => {
    $("apercu").replaceChildren();
    if (await essayer(() => appeler("indexer", {}))) await rafraichir(false);
  });
  $("arreter").addEventListener("click", () => essayer(() => appeler("arreter", {})));
}

async function demarrer() {
  brancher();
  if (!jeton) {
    alerter("Cette page doit être ouverte par Fouine lui-même. Fermez-la, puis relancez Fouine.");
    return;
  }
  const etat = await rafraichir(true);
  if (etat && etat.index.fichiers) $("question").focus();
}

document.addEventListener("DOMContentLoaded", demarrer);
