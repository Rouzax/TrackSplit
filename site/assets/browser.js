"use strict";
const A = "assets/";
let DATA = null;

async function init() {
  DATA = await (await fetch(A + "library.json")).json();
  renderTree();
}
document.addEventListener("DOMContentLoaded", init);

function renderTree() {
  const root = document.getElementById("browser-tree");
  root.innerHTML = "";
  for (const artist of DATA.artists) root.appendChild(renderArtist(artist));
}

function renderArtist(artist) {
  const el = document.createElement("div");
  el.className = "tree-node";

  const row = document.createElement("button");
  row.className = "tree-row tree-folder";
  row.type = "button";
  row.textContent = "📁 " + artist.name;

  const kids = document.createElement("div");
  kids.className = "tree-kids";
  for (const album of artist.albums) kids.appendChild(renderAlbum(album, artist));

  row.addEventListener("click", () => {
    kids.classList.toggle("open");
    if (artist.image) showCover(artist.image, artist.name);
  });

  el.appendChild(row);
  el.appendChild(kids);
  return el;
}

function renderAlbum(album, artist) {
  const row = document.createElement("button");
  row.className = "tree-row tree-album";
  row.type = "button";
  row.textContent = "💿 " + album.title;
  row.addEventListener("click", () => showAlbum(album, artist));
  return row;
}

function showCover(file, alt) {
  const img = document.getElementById("browser-cover");
  img.src = A + file;
  img.alt = alt;
}

function showAlbum(album, artist) {
  showCover(album.cover, album.title);
  const meta = document.getElementById("browser-meta");
  meta.hidden = false;

  const tracks = (album.tracks || []).map((t) => {
    const name = t.performer
      ? `${escapeHtml(t.performer)} - ${escapeHtml(t.title)}`
      : escapeHtml(t.title);
    const genre = t.genre
      ? `<span class="tgenre">${escapeHtml(t.genre)}</span>`
      : "";
    return `<li><span class="tnum">${escapeHtml(t.n)}</span>` +
      `<span class="tname">${name}</span>${genre}` +
      `<span class="tdur">${escapeHtml(t.duration || "")}</span></li>`;
  }).join("");

  meta.innerHTML = `
    <h3>${escapeHtml(album.title)}</h3>
    <p class="browser-sub">${escapeHtml(artist.name)} · ${escapeHtml(album.trackCount)} tracks</p>
    <ol class="tracklist">${tracks}</ol>`;
}

function escapeHtml(t) {
  return String(t).replace(/[&<>"']/g, (c) => (
    {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}
