"use strict";
// Interface de Fouine. Tout texte venu des fichiers est posé avec textContent,
// jamais interprété comme du HTML.

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

function nombre(n) { return n.toLocaleString("fr-FR"); }
function pluriel(n, mot) { return nombre(n) + " " + mot + (n > 1 ? "s" : ""); }
function taille(octets) {
  if (octets < 1024 * 1024) return Math.max(1, Math.round(octets / 1024)) + " Ko";
  return (octets / 1024 / 1024).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " Mo";
}

function alerter(message) {
  $("alerte").textContent = message || "";
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

// ------------------------------------------------------------------ onglets

function montrer(onglet) {
  for (const bouton of document.querySelectorAll(".onglet")) {
    if (bouton.dataset.onglet === onglet) bouton.setAttribute("aria-current", "page");
    else bouton.removeAttribute("aria-current");
  }
  $("chercher").hidden = onglet !== "chercher";
  $("regler").hidden = onglet !== "regler";
  if (onglet === "chercher") $("question").focus();
}

// ---------------------------------------------------------------- recherche

function surligner(texte, mots) {
  // Met en valeur les mots de la question, sans tenir compte des accents ni des majuscules.
  const morceau = document.createDocumentFragment();
  const sansAccent = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
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

function afficherResultats(question, resultats) {
  const zone = $("resultats");
  zone.replaceChildren();
  if (!resultats.length) {
    zone.append(el("p", { classe: "vide" }, "Rien trouvé pour cette recherche. Essayez avec d'autres mots."));
    return;
  }
  const mots = question.split(/\s+/).filter(Boolean);
  for (const r of resultats) {
    const ouvrir = (quoi) => () => essayer(() => appeler("ouvrir", { id: r.id, quoi }));
    zone.append(
      el("article", { classe: "resultat" },
        el("h3", {}, r.nom),
        el("p", { classe: "extrait" }, surligner(r.extrait, mots)),
        el("p", { classe: "ou" },
          el("span", { classe: "chemin" }, r.dossier),
          el("span", { classe: "discret" }, "Modifié le " + r.modifie)),
        el("p", { classe: "actions" },
          el("button", { type: "button", classe: "petit", clic: ouvrir("fichier") }, "Ouvrir le fichier"),
          el("button", { type: "button", classe: "petit", clic: ouvrir("dossier") }, "Ouvrir le dossier"))));
  }
}

async function chercher(evenement) {
  evenement.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  $("resultats").replaceChildren(el("p", { classe: "vide" }, "Recherche en cours…"));
  const reponse = await essayer(() => appeler("recherche", { question }));
  if (reponse) afficherResultats(question, reponse.resultats);
  else $("resultats").replaceChildren();
}

function afficherEtatIndex(etat) {
  const index = etat.index;
  if (!index.fichiers) {
    $("etat-index").textContent = "";
    if (!$("resultats").querySelector(".resultat")) {
      $("resultats").replaceChildren(
        el("div", { classe: "vide" },
          el("p", {}, "Aucun fichier n'est encore indexé."),
          el("p", {}, "Choisissez d'abord les dossiers que Fouine a le droit de lire."),
          el("button", { type: "button", classe: "principal", clic: () => montrer("regler") }, "Choisir mes dossiers")));
    }
    return;
  }
  if ($("resultats").querySelector(".vide button")) $("resultats").replaceChildren();
  let texte = pluriel(index.fichiers, "fichier") + " dans l'index";
  if (index.derniere_indexation) texte += " · mis à jour le " + index.derniere_indexation;
  if (etat.tache.en_cours) texte += " · indexation en cours";
  $("etat-index").textContent = texte;
}

// ----------------------------------------------------------------- réglages

function afficherReglages(etat) {
  reglages = etat.reglages;
  const liste = $("liste-dossiers");
  liste.replaceChildren();
  if (!reglages.dossiers.length) {
    liste.append(el("li", {}, el("span", { classe: "discret" }, "Aucun dossier pour l'instant.")));
  }
  for (const dossier of reglages.dossiers) {
    liste.append(
      el("li", {},
        el("span", { classe: "chemin" }, dossier),
        el("button", { type: "button", classe: "petit", "aria-label": "Retirer " + dossier,
          clic: () => changerDossiers(reglages.dossiers.filter((d) => d !== dossier)) }, "Retirer")));
  }
  const propositions = $("propositions");
  propositions.replaceChildren();
  for (const dossier of etat.dossiers_proposes.filter((d) => !reglages.dossiers.includes(d))) {
    const nom = dossier.split(/[\\/]/).filter(Boolean).pop();
    propositions.append(
      el("button", { type: "button", classe: "petit", title: dossier,
        clic: () => changerDossiers(reglages.dossiers.concat([dossier])) }, "+ " + nom));
  }
  $("extensions").value = reglages.extensions.join(" ");
  $("taille").value = reglages.taille_max_mo;
  $("exclus").value = reglages.dossiers_exclus.join("\n");
  $("caches").checked = reglages.inclure_caches;
  $("sensibles").replaceChildren(...reglages.motifs_sensibles.flatMap((m) => [el("span", {}, m), " "]));
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
    liste.append(el("li", {}, el("button", { type: "button", clic: () => allerDans(reponse.parent) }, "↑ Remonter d'un niveau")));
  }
  for (const sous of reponse.sous_dossiers) {
    liste.append(el("li", {}, el("button", { type: "button", clic: () => allerDans(sous.chemin) }, sous.nom)));
  }
  if (!reponse.sous_dossiers.length) {
    liste.append(el("li", { classe: "vide" }, "Pas de sous-dossier ici."));
  }
}

// ------------------------------------------------------ aperçu et indexation

function afficherApercu(a) {
  const zone = $("apercu");
  zone.replaceChildren();
  const ecartes = a.ecartes.reduce((s, g) => s + g.fichiers + g.dossiers, 0);
  const types = Object.entries(a.acceptes.par_type).sort((x, y) => y[1] - x[1])
    .map(([ext, n]) => nombre(n) + " " + ext).join(" · ");
  zone.append(
    el("div", { classe: "chiffres" },
      el("div", { classe: "chiffre lus" }, el("strong", {}, nombre(a.acceptes.nombre)),
        (a.acceptes.nombre > 1 ? "fichiers seraient lus" : "fichier serait lu") + " (" + taille(a.acceptes.taille) + ")"),
      el("div", { classe: "chiffre" }, el("strong", {}, nombre(ecartes)),
        ecartes > 1 ? "fichiers ou dossiers laissés de côté" : "fichier ou dossier laissé de côté")));
  if (types) zone.append(el("p", { classe: "discret" }, "Lus : " + types));
  for (const absent of a.introuvables) {
    zone.append(el("p", { classe: "alerte" }, "Dossier introuvable en ce moment : " + absent));
  }
  if (a.acceptes.exemples.length) {
    zone.append(el("details", {}, el("summary", {}, "Exemples de fichiers lus"),
      el("ul", { classe: "raisons-liste" }, ...a.acceptes.exemples.map((c) => el("li", { classe: "chemin" }, c)))));
  }
  if (!a.ecartes.length) return;
  const corps = el("tbody", {});
  for (const g of a.ecartes) {
    const combien = [g.fichiers ? pluriel(g.fichiers, "fichier") : "", g.dossiers ? pluriel(g.dossiers, "dossier") : ""]
      .filter(Boolean).join(", ");
    corps.append(el("tr", {},
      el("td", {}, g.raison),
      el("td", { classe: "nombre" }, combien),
      el("td", {}, el("ul", {}, ...g.exemples.map((c) => el("li", { classe: "chemin" }, c))))));
  }
  zone.append(el("table", { classe: "raisons" },
    el("thead", {}, el("tr", {}, el("th", {}, "Laissé de côté parce que"), el("th", {}, "Combien"), el("th", {}, "Exemples"))),
    corps));
  zone.append(el("p", { classe: "aide" }, "Un dossier laissé de côté n'est pas ouvert : il compte pour un, quel que soit son contenu."));
}

function phraseBilan(b) {
  const lus = b.nouveaux + b.modifies;
  const morceaux = [
    pluriel(lus, "fichier") + (lus > 1 ? " lus" : " lu"),
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
    el("ul", { classe: "raisons-liste" },
      ...reponse.illisibles.map((i) => el("li", {}, el("span", { classe: "chemin" }, i.chemin), " — " + i.erreur)))));
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
    let texte;
    if (t.etape === "modele") {
      barre.removeAttribute("value");
      texte = "Préparation du modèle. La toute première fois, il est téléchargé (" + etat.taille_modele + ") : cela peut prendre quelques minutes.";
    } else if (t.etape === "lecture" && t.total) {
      barre.value = Math.round((t.fait / t.total) * 100);
      texte = "Fichier " + nombre(t.fait + 1) + " sur " + nombre(t.total) + " : " + t.fichier;
    } else {
      barre.removeAttribute("value");
      texte = "Recherche des fichiers nouveaux ou modifiés…";
    }
    $("texte-progression").textContent = texte;
    $("bilan").hidden = true;
  } else if (t.erreur || t.bilan) {
    $("bilan").hidden = false;
    $("bilan").classList.toggle("erreur", Boolean(t.erreur));
    $("bilan").textContent = t.erreur ? "L'indexation s'est arrêtée sur une erreur : " + t.erreur : phraseBilan(t.bilan);
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
  $("form-recherche").addEventListener("submit", chercher);
  for (const id of ["extensions", "taille", "exclus", "caches"]) {
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
    alerter("Cette page doit être ouverte par Fouine lui-même. Fermez-la, puis relancez Fouine (lancer.bat).");
    return;
  }
  const etat = await rafraichir(true);
  if (etat && !etat.index.fichiers) montrer("regler");
  else $("question").focus();
}

demarrer();
