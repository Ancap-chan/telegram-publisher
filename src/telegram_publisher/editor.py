"""Локальное окно визуального редактора публикаций."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
from pathlib import Path

import webview

from . import __version__

from .importer import import_from_file, import_from_url
from .profiles import ChannelProfile, delete_profile, load_profiles, save_profile
from .controller import PublicationController, PublicationRequest
from .publishing import PartialPublicationError


EDITOR_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Редактор публикации</title>
<style>
:root{font:16px "Segoe UI",sans-serif;color:#222;background:#f4f5f7}
*{box-sizing:border-box}
body{margin:0;display:flex;flex-direction:column;height:100vh}
header{padding:10px;background:#fff;border-bottom:1px solid #ddd;display:flex;flex-direction:column;gap:8px;align-items:stretch}.toolbar-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;width:100%}.heading-tool{padding:4px 7px;font-size:12px;min-width:34px}.plain-unsupported{outline:2px dashed #c87919!important;background-color:#fff3d8!important}.plain-unsupported::after{content:"";display:inline-block}
button,select{font:inherit;padding:7px 10px;border:1px solid #ccc;border-radius:4px;background:#fff;cursor:pointer}
button:hover{background:#eee}
main{flex:1;overflow:auto;padding:24px}
#editor{max-width:1000px;min-height:calc(100vh - 190px);margin:0 auto;background:#fff;padding:32px;box-shadow:0 1px 5px #0001;outline:none;line-height:1.55;overflow-wrap:anywhere}
#editor img,#editor video{max-width:100%;height:auto}
#editor table{border-collapse:collapse;width:100%}
#editor td,#editor th{border:1px solid #888;padding:6px}
footer{padding:10px 14px;background:#fff;border-top:1px solid #ddd;display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.status{color:#555;font-size:13px}
.publish-options{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.context-menu{position:fixed;z-index:1000;min-width:150px;padding:4px;background:#fff;border:1px solid #bbb;border-radius:5px;box-shadow:0 3px 12px #0002}
.context-menu[hidden]{display:none}
.context-menu button{display:block;width:100%;text-align:left;border:0;background:transparent;padding:7px 10px}
.context-menu button:hover{background:#eee}
#publish{font-weight:600}
.series-break{display:block;position:relative;margin:14px 0;padding:8px 12px;border:2px dashed #789;border-radius:5px;background:#eef3f8;color:#34495e;text-align:center;font-size:13px;cursor:default;user-select:none}.series-break.selected{outline:2px solid #2457a7;background:#dce8fa}.series-status{padding:8px 14px;background:#f4f5f7;border-bottom:1px solid #ddd;font-size:13px;white-space:pre-wrap}.series-status.warning{color:#a21d1d;font-weight:600}#series-tools{display:none}#series-tools.visible{display:inline-flex;gap:6px;align-items:center}
</style>
</head>
<body>
<header>
<div class="toolbar-row file-tools"><button id="import-url">Импортировать по ссылке</button><button id="import-file">Открыть файл…</button><button id="save-draft">Сохранить черновик…</button><button id="manual" style="margin-left:auto">Руководство</button></div>
<div class="toolbar-row edit-tools"><button data-cmd="bold"><b>Жирный</b></button><button data-cmd="italic"><i>Курсив</i></button><button data-cmd="underline"><u>Подчёркнутый</u></button><button data-cmd="strikeThrough"><s>Зачёркнутый</s></button>
<button data-cmd="insertUnorderedList">• Список</button><button data-cmd="insertOrderedList">1. Список</button><button data-cmd="formatBlock" data-value="blockquote">Цитата</button><button class="heading-tool" data-cmd="formatBlock" data-value="h1" data-rich-only>H1</button><button class="heading-tool" data-cmd="formatBlock" data-value="h2" data-rich-only>H2</button><button class="heading-tool" data-cmd="formatBlock" data-value="h3" data-rich-only>H3</button><button class="heading-tool" data-cmd="formatBlock" data-value="h4" data-rich-only>H4</button><button class="heading-tool" data-cmd="formatBlock" data-value="h5" data-rich-only>H5</button><button class="heading-tool" data-cmd="formatBlock" data-value="h6" data-rich-only>H6</button><button data-cmd="formatBlock" data-value="p">Абзац</button>
<button id="link">Ссылка</button><button id="media">Медиа по URL</button><button id="local-media" hidden>Медиа из файла</button><button id="table" data-rich-only>Таблица</button><button data-cmd="removeFormat">Очистить формат</button><span id="series-tools"><button id="insert-break">Разрыв сообщения</button></span></div>
</header>
<div id="series-status" class="series-status" aria-live="polite" hidden></div><main><div id="editor" contenteditable="true" spellcheck="true"></div></main>
<div id="context-menu" class="context-menu" hidden>
<button data-edit="cut">Вырезать</button>
<button data-edit="copy">Копировать</button>
<button data-edit="paste">Вставить</button>
<button data-action="insert-break">Вставить разрыв сообщения</button>
<button data-action="delete-break">Удалить разрыв</button>
</div>
<footer>
<div class="publish-options">
<label for="channel">Канал:</label><select id="channel" aria-label="Канал"></select>
<label for="mode">Способ публикации:</label><select id="mode" aria-label="Способ публикации">
<option value="plain">Обычное сообщение (минимальное форматирование, размер до 4096 символов)</option>
<option value="rich">Рич-сообщение (полноценное форматирование, размер до 32768 символов)</option>
<option value="album">Альбом из 2–10 медиа с общей подписью (до 1024 символов)</option>
<option value="plain_series">Серия обычных сообщений</option>
<option value="rich_series">Серия рич-сообщений</option>
<option value="album_series">Серия альбомов (2–10 медиа и отдельная подпись на каждый альбом)</option>
</select>
<label><input id="series" type="checkbox"> Разбить на серию постов</label>
</div>
<div class="publish-options">
<button id="manage">Настроить каналы…</button>
<button id="retry-pending" hidden>Повторить оставшиеся сообщения</button>
<button id="publish">Опубликовать</button>
</div>
<span class="status" id="status">Вставка через Ctrl+V сохраняет доступное форматирование. Медиа можно добавлять по публичному URL, а в рич-сообщениях и альбомах — также из локальных файлов.</span>
</footer>
<script>
const editor=document.getElementById('editor');
const contextMenu=document.getElementById('context-menu');
const channelSelect=document.getElementById('channel');
const modeSelect=document.getElementById('mode');
let lastModeValue=modeSelect.value;
const seriesCheckbox=document.getElementById('series');
let savedRange=null;
let selectedBreak=null;
let config={profiles:[],selected_profile_id:null,mode:'rich',series:false,status:''};
function applyConfig(value){
 config=value||config;
 editor.innerHTML=window.initialContent||'';
 channelSelect.replaceChildren();
 for(const profile of (config.profiles||[])){
  const option=document.createElement('option');
  option.value=profile.profile_id;
  option.textContent=profile.name+' — '+profile.chat_id;
  channelSelect.append(option);
 }
 if(config.selected_profile_id)channelSelect.value=config.selected_profile_id;
 modeSelect.value=config.mode||'rich';
 lastModeValue=modeSelect.value;
 seriesCheckbox.checked=Boolean(config.series)||modeSelect.value.endsWith('_series');
 if(!channelSelect.value&&channelSelect.options.length)channelSelect.selectedIndex=0;
 if(config.status)document.getElementById('status').textContent=config.status;
 else if(!channelSelect.options.length)document.getElementById('status').textContent='Сначала укажите канал для публикации с помощью кнопки «Настроить каналы…».';
 updateModeUI();
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
}
function rememberEditorSelection(){
 const selection=window.getSelection();
 if(!selection||!selection.rangeCount)return;
 const range=selection.getRangeAt(0);
 if(range.commonAncestorContainer===editor||editor.contains(range.commonAncestorContainer))savedRange=range.cloneRange();
}
function restoreEditorSelection(){
 editor.focus();
 if(!savedRange)return false;
 const selection=window.getSelection();
 selection.removeAllRanges();
 selection.addRange(savedRange);
 return true;
}
function cleanClipboardHtml(markup){
 const parsed=new DOMParser().parseFromString(markup,'text/html');
 const sourceMatch=String(markup).match(/(?:SourceURL:|sourceurl\s*=\s*["'])(https?:\/\/[^\s"'<>]+)/i);
 let baseUrl=sourceMatch?sourceMatch[1]:null;
 const baseElement=parsed.querySelector('base[href]');
 if(baseElement&&/^https?:\/\//i.test(baseElement.href))baseUrl=baseElement.href;
 let removedImages=0;
 const publicUrl=value=>{
  const candidate=String(value||'').trim();
  if(!candidate||candidate.startsWith('data:')||candidate.startsWith('blob:'))return null;
  try{
   const resolved=new URL(candidate,baseUrl||undefined);
   return /^https?:$/.test(resolved.protocol)?resolved.href:null;
  }catch(_error){return null}
 };
 const srcsetUrl=value=>{
  if(!value)return null;
  for(const item of value.split(',')){
   const resolved=publicUrl(item.trim().split(/\s+/)[0]);
   if(resolved)return resolved;
  }
  return null;
 };
 for(const image of Array.from(parsed.querySelectorAll('img'))){
  const candidates=[
   image.getAttribute('src'),
   image.getAttribute('data-src'),
   image.getAttribute('data-original'),
   image.getAttribute('data-lazy-src'),
   srcsetUrl(image.getAttribute('srcset')),
   srcsetUrl(image.getAttribute('data-srcset'))
  ];
  let imageUrl=null;
  for(const candidate of candidates){
   imageUrl=publicUrl(candidate);
   if(imageUrl)break;
  }
  if(!imageUrl){image.remove();removedImages++;continue}
  image.setAttribute('src',imageUrl);
  for(const attribute of ['srcset','data-src','data-original','data-lazy-src','data-srcset','loading'])image.removeAttribute(attribute);
 }
 for(const video of Array.from(parsed.querySelectorAll('video'))){
  const url=publicUrl(video.getAttribute('src')||video.querySelector('source')?.getAttribute('src'));
  if(!url){video.remove();continue}
  video.setAttribute('src',url);
  video.querySelectorAll('source').forEach(source=>source.remove());
 }
 parsed.querySelectorAll('script,style,base,meta,link').forEach(node=>node.remove());
 return {html:parsed.body.innerHTML,removedImages};
}
function insertClipboardHtml(markup){
 const cleaned=cleanClipboardHtml(markup);
 restoreEditorSelection();
 document.execCommand('insertHTML',false,cleaned.html);
 rememberEditorSelection();
 updateSeriesStatus();
 if(cleaned.removedImages){
  document.getElementById('status').textContent=cleaned.removedImages===1
   ?'Вставка изображения из буфера пропущено: не удалось определить его публичный URL. Вставьте изображение по ссылке.'
   :'Вставка изображений из буфера пропущена: не удалось определить их публичные URL. Вставьте изображения по ссылкам.';
 }
}
function blobToDataUrl(blob){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(String(reader.result||''));
  reader.onerror=()=>reject(reader.error||new Error('Не удалось прочитать изображение из буфера.'));
  reader.readAsDataURL(blob);
 });
}
function hideContextMenu(){contextMenu.hidden=true}
editor.addEventListener('mouseup',rememberEditorSelection);
editor.addEventListener('keyup',rememberEditorSelection);
editor.addEventListener('input',rememberEditorSelection);
editor.addEventListener('paste',event=>{
 const clipboard=event.clipboardData;
 if(!clipboard)return;
 const markup=clipboard.getData('text/html');
 if(markup){
  event.preventDefault();
  insertClipboardHtml(markup);
  return;
 }
});
document.addEventListener('selectionchange',rememberEditorSelection);
editor.addEventListener('click',event=>{
 const marker=event.target.closest('.series-break');
 if(marker&&isSeriesMode()){
  if(selectedBreak)selectedBreak.classList.remove('selected');
  selectedBreak=marker;
  marker.classList.add('selected');
 }else{
  if(selectedBreak)selectedBreak.classList.remove('selected');
  selectedBreak=null;
 }
});
editor.addEventListener('contextmenu',event=>{
 event.preventDefault();
 const marker=event.target.closest('.series-break');
 if(selectedBreak&&selectedBreak!==marker)selectedBreak.classList.remove('selected');
 selectedBreak=marker||null;
 if(selectedBreak)selectedBreak.classList.add('selected');
 else{
  const selection=window.getSelection();
  const hasSelection=selection&&selection.rangeCount&&!selection.getRangeAt(0).collapsed&&editor.contains(selection.anchorNode)&&editor.contains(selection.focusNode);
  if(hasSelection)rememberEditorSelection();
  else{
   let pointRange=null;
   if(document.caretRangeFromPoint)pointRange=document.caretRangeFromPoint(event.clientX,event.clientY);
   else if(document.caretPositionFromPoint){
    const position=document.caretPositionFromPoint(event.clientX,event.clientY);
    if(position){pointRange=document.createRange();pointRange.setStart(position.offsetNode,position.offset);pointRange.collapse(true)}
   }
   if(pointRange&&(pointRange.commonAncestorContainer===editor||editor.contains(pointRange.commonAncestorContainer)))savedRange=pointRange.cloneRange();
   else rememberEditorSelection();
  }
 }
 contextMenu.querySelector('[data-action="insert-break"]').hidden=!isSeriesMode();
 contextMenu.querySelector('[data-action="delete-break"]').hidden=!selectedBreak;
 contextMenu.hidden=false;
 const x=Math.min(event.clientX,window.innerWidth-contextMenu.offsetWidth-8);
 const y=Math.min(event.clientY,window.innerHeight-contextMenu.offsetHeight-8);
 contextMenu.style.left=Math.max(8,x)+'px';
 contextMenu.style.top=Math.max(8,y)+'px';
});
document.addEventListener('pointerdown',event=>{if(!contextMenu.contains(event.target))hideContextMenu()});
document.addEventListener('keydown',event=>{
 if(event.key==='Escape')hideContextMenu();
 if(selectedBreak&&(event.key==='Delete'||event.key==='Backspace')){
  event.preventDefault();
  selectedBreak.remove();
  selectedBreak=null;
  updateSeriesStatus();
 }
});
contextMenu.querySelectorAll('[data-edit]').forEach(button=>button.addEventListener('click',async()=>{
 const action=button.dataset.edit;
 hideContextMenu();
 restoreEditorSelection();
 if(action==='cut'||action==='copy'){
  document.execCommand(action,false,null);
  rememberEditorSelection();
  updateSeriesStatus();
  return;
 }
 try{
  if(navigator.clipboard&&navigator.clipboard.read){
   const items=await navigator.clipboard.read();
   for(const item of items){
    if(item.types.includes('text/html')){
     const blob=await item.getType('text/html');
     insertClipboardHtml(await blob.text());
     return;
    }
    const imageType=item.types.find(type=>type.startsWith('image/'));
    if(imageType){
     const blob=await item.getType(imageType);
     const dataUrl=await blobToDataUrl(blob);
     const safe=dataUrl.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
     insertClipboardHtml('<img src="'+safe+'" alt="">');
     return;
    }
    if(item.types.includes('text/plain')){
     const blob=await item.getType('text/plain');
     restoreEditorSelection();
     document.execCommand('insertText',false,await blob.text());
     rememberEditorSelection();
     updateSeriesStatus();
     return;
    }
   }
  }
  const text=await navigator.clipboard.readText();
  restoreEditorSelection();
  document.execCommand('insertText',false,text);
  rememberEditorSelection();
  updateSeriesStatus();
 }catch(error){
  restoreEditorSelection();
  document.execCommand('paste',false,null);
  rememberEditorSelection();
  updateSeriesStatus();
 }
}));
contextMenu.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>{
 const action=button.dataset.action;
 hideContextMenu();
 if(action==='insert-break')insertBreakAtSelection();
 if(action==='delete-break'&&selectedBreak){
  selectedBreak.remove();
  selectedBreak=null;
  updateSeriesStatus();
 }
}));
async function setImportedContent(promise){
 const status=document.getElementById('status');
 status.textContent='Импорт…';
 try{
  const html=await promise;
  if(html===null||html===undefined)return;
  if(!String(html).trim())throw new Error('В источнике не найден текст.');
  editor.innerHTML=html;
  if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
  updateModeUI();
  status.textContent='Импорт завершён. Проверьте содержимое и при необходимости отредактируйте его.';
  editor.focus();
 }catch(error){status.textContent='Не удалось импортировать: '+(error&&error.message?error.message:String(error));}
}
document.getElementById('import-url').onclick=async()=>{
 const url=prompt('Вставьте ссылку на публикацию или страницу','https://');
 if(!url)return;
 const trimmedUrl=url.trim();
 if(!trimmedUrl.toLowerCase().startsWith('http://')&&!trimmedUrl.toLowerCase().startsWith('https://')){document.getElementById('status').textContent='Укажите полный URL, начинающийся с http:// или https://.';return;}
 await setImportedContent(window.pywebview.api.import_url(url.trim()));
};
document.getElementById('import-file').onclick=async()=>{
 const status=document.getElementById('status');
 try{
  const selected=await window.pywebview.api.open_file();
  if(!selected)return;
  if(selected.type==='draft'){
   applyDraft(selected.draft);
   status.textContent='Черновик загружен.';
  }else if(selected.type==='content'){
   await setImportedContent(Promise.resolve(selected.html));
  }else{
   throw new Error('Неизвестный формат файла.');
  }
 }catch(error){
  status.textContent='Не удалось открыть файл: '+(error&&error.message?error.message:String(error));
 }
};
function currentDraft(){
 return {
  format:'telegram-publisher-draft',
  version:1,
  html:editor.innerHTML,
  mode:modeSelect.value,
  series:isSeriesMode(),
  profile_id:channelSelect.value||null
 };
}
function draftFilename(){
 const heading=editor.querySelector('h1,h2,h3,h4,h5,h6');
 let title=heading?(heading.innerText||heading.textContent||'').trim():'';
 if(!title){
  const clone=editor.cloneNode(true);
  clone.querySelectorAll('.series-break').forEach(node=>node.remove());
  const text=(clone.innerText||clone.textContent||'').replace(/\s+/g,' ').trim();
  title=text.split(' ').filter(Boolean).slice(0,3).join(' ');
 }
 title=title.replace(/[<>:"/\\|?*\x00-\x1f]/g,' ').replace(/\s+/g,' ').trim().replace(/[. ]+$/,'');
 return (title||'Черновик').slice(0,100);
}
function applyDraft(draft){
 if(!draft||draft.format!=='telegram-publisher-draft'||draft.version!==1||
    typeof draft.html!=='string'||
    !['rich','plain','rich_series','plain_series','album','album_series'].includes(draft.mode)||
    typeof draft.series!=='boolean'){
  throw new Error('Файл не является поддерживаемым черновиком Telegram Publisher.');
 }
 editor.innerHTML=draft.html;
 modeSelect.value=draft.mode;
 seriesCheckbox.checked=draft.series;
 channelSelect.value=draft.profile_id||'';
 updateModeUI();
 editor.focus();
}
document.getElementById('save-draft').onclick=async()=>{
 const status=document.getElementById('status');
 try{
  const saved=await window.pywebview.api.save_draft(currentDraft(),draftFilename());
  if(saved)status.textContent='Черновик сохранён: '+saved;
 }catch(error){
  status.textContent='Не удалось сохранить черновик: '+(error&&error.message?error.message:String(error));
 }
};
document.getElementById('manual').onclick=async()=>{
 try{await window.pywebview.api.open_manual()}
 catch(error){document.getElementById('status').textContent='Не удалось открыть руководство: '+(error&&error.message?error.message:String(error));}
};
document.querySelectorAll('[data-cmd]').forEach(button=>button.addEventListener('click',()=>{
 editor.focus();const cmd=button.dataset.cmd;document.execCommand(cmd,false,button.dataset.value||null);
}));
function askUrl(label){const value=prompt(label,'https://');return value&&/^https?:\/\//i.test(value)?value.trim():null}
document.getElementById('link').onclick=()=>{const url=askUrl('Публичный URL ссылки');if(url){editor.focus();document.execCommand('createLink',false,url)}};
function currentPartMediaCount(){
 if(!isSeriesMode())return partMediaCount(Array.from(editor.childNodes).filter(node=>!(node.nodeType===1&&node.classList.contains('series-break'))));
 const selection=window.getSelection();
 let selected=selection&&selection.anchorNode;
 while(selected&&selected.parentNode!==editor)selected=selected.parentNode;
 const rawParts=[[]];
 let selectedIndex=0;
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break')){rawParts.push([]);continue}
  rawParts[rawParts.length-1].push(node);
  if(selected&&(node===selected||node.contains&&node.contains(selected)))selectedIndex=rawParts.length-1;
 }
 return partMediaCount(rawParts[selectedIndex]||[]);
}
async function insertMediaFromFile(){
 if(!isRichMode()&&!isAlbumMode())return;
 const status=document.getElementById('status');
 try{
  const files=await window.pywebview.api.select_media_files();
  if(!files||!files.length)return;
  const currentCount=currentPartMediaCount();
  if(isAlbumMode()&&currentCount+files.length>10){
   status.textContent='В одном альбоме допускается не более 10 изображений или видео.';
   return;
  }
  const markup=files.map(file=>{
   const path=String(file.path||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
   const uri=String(file.uri||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
   if(file.type==='video')return '<p><video controls data-local-file="'+path+'" src="'+uri+'"></video></p>';
   return '<p><img data-local-file="'+path+'" src="'+uri+'" alt=""></p>';
  }).join('');
  editor.focus();
  document.execCommand('insertHTML',false,markup);
  status.textContent='Локальные медиа добавлены. Они поддерживаются в рич-сообщениях и альбомах.';
  updatePlainCompatibility();
  updateSeriesStatus();
 }catch(error){
  status.textContent='Не удалось добавить медиа из файла: '+(error&&error.message?error.message:String(error));
 }
}
function insertMediaFromUrl(){
 if(isAlbumMode()&&currentPartMediaCount()>=10){document.getElementById('status').textContent='В одном альбоме допускается не более 10 изображений или видео.';return}
 if(!isRichMode()&&!isAlbumMode()&&currentPartMediaCount()>=1){document.getElementById('status').textContent='В одном обычном сообщении допускается только одно изображение или видео.';return}
 const url=askUrl('Публичный URL изображения или видео');
 if(!url)return;
 let parsed;
 try{parsed=new URL(url)}catch(error){document.getElementById('status').textContent='Не удалось разобрать адрес.';return}
 const host=parsed.hostname.toLowerCase().replace(/^www\./,'');
 const isVideoSite=host==='youtube.com'||host.endsWith('.youtube.com')||host==='youtu.be'||host==='youtube-nocookie.com'||host.endsWith('.youtube-nocookie.com');
 if(isVideoSite){
  if(isAlbumMode()){document.getElementById('status').textContent='Для альбома укажите прямой публичный URL файла изображения или видео, а не страницу видеохостинга.';return}
  const safe=url.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
  editor.focus();
  document.execCommand('insertHTML',false,'<p><a href="'+safe+'" data-publication-media-preview="video">'+safe+'</a></p>');
  document.getElementById('status').textContent=isRichMode()
   ?'Это страница сайта видеохостинга, а не адрес видеофайла. Такой способ импорта годится для публикации в виде обычного сообщения, но не рич-сообщения. Для встраивания видео в рич-сообщение укажите прямой URL файла.'
   :'При публикации ссылка на видеосайт будет скрыта, а её URL передан Telegram для предпросмотра.';
  updateSeriesStatus();
  return;
 }
 const path=parsed.pathname+parsed.search+parsed.hash;
 const videoByExtension=/\.(mp4|m4v|mov|webm|mkv)(?:$|[?#])/i.test(path);
 const imageByExtension=/\.(png|jpe?g|gif|webp|avif|bmp)(?:$|[?#])/i.test(path);
 const kind=videoByExtension?'video':imageByExtension?'image':(confirm('Это прямой URL видеофайла?\nНажмите «ОК» для видео или «Отмена» для изображения.')?'video':'image');
 editor.focus();
 const safe=url.replace(/&/g,'&amp;').replace(/"/g,'&quot;');
 const markup=kind==='image'?'<p><img src="'+safe+'" alt=""></p>':'<p><video controls src="'+safe+'"></video></p>';
 document.execCommand('insertHTML',false,markup);
 updatePlainCompatibility();
 updateSeriesStatus();
}
document.getElementById('media').onclick=insertMediaFromUrl;
document.getElementById('local-media').onclick=insertMediaFromFile;
document.getElementById('table').onclick=()=>{const rows=Math.max(1,Math.min(20,Number(prompt('Количество строк','2'))||2));const cols=Math.max(1,Math.min(10,Number(prompt('Количество столбцов','2'))||2));let table='<table><tbody>';for(let r=0;r<rows;r++){table+='<tr>';for(let c=0;c<cols;c++)table+='<td><br></td>';table+='</tr>'}table+='</tbody></table><p><br></p>';editor.focus();document.execCommand('insertHTML',false,table)};
const seriesStatus=document.getElementById('series-status');
function isAlbumMode(){return modeSelect.value==='album'||modeSelect.value==='album_series'}
function isSeriesMode(){return modeSelect.value.endsWith('_series')||(!isAlbumMode()&&seriesCheckbox.checked)}
function isRichMode(){return modeSelect.value==='rich'||modeSelect.value==='rich_series'||modeSelect.value==='media_text'}
function messageLimit(){return isAlbumMode()?1024:(isRichMode()?32768:4096)}
function makeBreak(){
 const marker=document.createElement('div');
 marker.className='series-break';
 marker.contentEditable='false';
 marker.draggable=false;
 marker.dataset.postBreak='1';
 marker.textContent='Разрыв сообщения — нажмите Del, чтобы удалить';
 return marker;
}
function partNodes(){
 const parts=[[]];
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break')){parts.push([]);continue}
  parts[parts.length-1].push(node);
 }
 return parts.filter(nodes=>{
  const wrapper=document.createElement('div');
  for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
  return Boolean((wrapper.innerText||wrapper.textContent||'').trim()||wrapper.querySelector('img,video'));
 });
}
function htmlParts(){
 return partNodes().map(nodes=>{
  const wrapper=document.createElement('div');
  for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
  return wrapper.innerHTML.trim();
 }).filter(part=>part.length>0);
}
function partLength(nodes){
 const wrapper=document.createElement('div');
 for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
 wrapper.querySelectorAll('.series-break').forEach(node=>node.remove());
 return (wrapper.innerText||wrapper.textContent||'').trim().length;
}
function partMediaCount(nodes){
 const wrapper=document.createElement('div');
 for(const node of nodes)wrapper.appendChild(node.cloneNode(true));
 return wrapper.querySelectorAll('img,video').length;
}
function updateSeriesStatus(){
 const series=isSeriesMode();
 const parts=series?partNodes():[Array.from(editor.childNodes).filter(node=>!(node.nodeType===1&&node.classList.contains('series-break')))];
 const limit=messageLimit();
 const enforceSingleMedia=!isRichMode()&&!isAlbumMode();
 const lengths=parts.map(partLength);
 const mediaCounts=parts.map(partMediaCount);
 const hasContent=parts.some((part,index)=>lengths[index]>0||mediaCounts[index]>0);
 seriesStatus.hidden=!hasContent;
 const overflow=lengths.some(length=>length>limit);
 const tooMuchMedia=enforceSingleMedia&&mediaCounts.some(count=>count>1);
 const albumInvalid=isAlbumMode()&&mediaCounts.some(count=>count<2||count>10);
 seriesStatus.classList.toggle('warning',overflow||tooMuchMedia||albumInvalid);
 if(!hasContent){seriesStatus.textContent='';return true}
 seriesStatus.textContent=parts.map((part,index)=>{
  const prefix=series?'Пост '+(index+1):'Сообщение';
  const notes=[];
  if(lengths[index]>limit)notes.push(isAlbumMode()?'подпись к альбому ограничена 1024 символами':'превышен лимит, перенесите часть текста');
  else if(lengths[index]===limit)notes.push('лимит заполнен, больше не стоит сюда ничего добавлять');
  if(enforceSingleMedia&&mediaCounts[index]>1)notes.push('допускается не более одного изображения или видео на пост');
  if(isAlbumMode()&&mediaCounts[index]<2)notes.push('для альбома требуется не менее двух медиа');
  if(isAlbumMode()&&mediaCounts[index]>10)notes.push('в одном альбоме допускается не более 10 медиа');
  return prefix+': '+lengths[index]+'/'+limit+' символов'+(mediaCounts[index]?' · медиа: '+mediaCounts[index]:'')+(notes.length?' — '+notes.join('; ')+'.':'');
 }).join('\n');
 return !overflow&&!tooMuchMedia&&!albumInvalid;
}
const PLAIN_SUBSTITUTIONS=[
 {selector:'h1,h2,h3,h4,h5,h6',message:'Уровень заголовка будет заменён жирным текстом.'},
 {selector:'table',message:'Таблица будет преобразована в текстовые строки.'},
 {selector:'img,video',message:'Медиа будет заменено скрытой ссылкой для предпросмотра.'},
 {selector:'mark,sub,sup,small,big,font,span[style]',message:'Это оформление не поддерживается в обычном режиме; текст сохранится.'}
];
function updatePlainCompatibility(){
 editor.querySelectorAll('.plain-unsupported').forEach(node=>{
  node.classList.remove('plain-unsupported');
  if(node.dataset.plainOriginalTitle!==undefined){
   if(node.dataset.plainOriginalTitle)node.title=node.dataset.plainOriginalTitle;
   else node.removeAttribute('title');
   delete node.dataset.plainOriginalTitle;
  }
 });
 if(isRichMode()||isAlbumMode())return;
 for(const rule of PLAIN_SUBSTITUTIONS){
  editor.querySelectorAll(rule.selector).forEach(node=>{
   node.classList.add('plain-unsupported');
   node.dataset.plainOriginalTitle=node.getAttribute('title')||'';
   node.title=rule.message;
  });
 }
}
function updateModeUI(){
 const rich=isRichMode();
 document.getElementById('local-media').hidden=!rich&&!isAlbumMode();
 document.querySelectorAll('[data-rich-only]').forEach(button=>button.hidden=!rich);
 document.getElementById('series-tools').classList.toggle('visible',isSeriesMode());
 seriesCheckbox.disabled=isAlbumMode();
 if(isAlbumMode())seriesCheckbox.checked=false;
 else seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 updatePlainCompatibility();
 updateSeriesStatus();
}
function preferredSplitBoundary(text,start,end,limit){
 const segment=text.slice(start,end);
 const sentencePattern=/[.!?…]+(?:["'»”’)}\]]*)\s+/g;
 let match,lastSentenceBoundary=0;
 while((match=sentencePattern.exec(segment))!==null){
  const boundary=start+match.index+match[0].trimEnd().length;
  if(boundary>start+Math.floor(limit*0.5))lastSentenceBoundary=boundary;
 }
 if(lastSentenceBoundary>start)return lastSentenceBoundary;
 const newline=text.lastIndexOf('\n',end);
 const space=text.lastIndexOf(' ',end);
 const boundary=Math.max(newline,space);
 return boundary>start+Math.floor(limit*0.5)?boundary:end;
}
function splitOversizedList(node,limit){
 const items=Array.from(node.children).filter(item=>item.tagName==='LI');
 if(!items.length)return [node];
 const chunks=[];
 let current=node.cloneNode(false),used=0;
 const flush=()=>{
  if(current.children.length)chunks.push(current);
  current=node.cloneNode(false);
  used=0;
 };
 for(const item of items){
  const itemLength=(item.innerText||item.textContent||'').trim().length;
  const pieces=itemLength>limit?splitOversizedNode(item,limit):[item];
  for(const piece of pieces){
   const length=(piece.innerText||piece.textContent||'').trim().length;
   const separator=current.children.length?1:0;
   if(current.children.length&&used+separator+length>limit)flush();
   const nextSeparator=current.children.length?1:0;
   current.appendChild(piece.cloneNode(true));
   used+=nextSeparator+length;
  }
 }
 flush();
 return chunks.length?chunks:[node];
}
function splitOversizedNode(node,limit){
 const originalText=node.textContent||'';
 if(node.nodeType===Node.ELEMENT_NODE&&['UL','OL'].includes(node.tagName)&&(node.innerText||originalText).trim().length>limit){
  return splitOversizedList(node,limit);
 }
 if(originalText.length<=limit)return [node];
 if(node.nodeType===Node.TEXT_NODE){
  const chunks=[];
  let start=0;
  while(start<originalText.length){
   let end=Math.min(start+limit,originalText.length);
   if(end<originalText.length){
    const boundary=preferredSplitBoundary(originalText,start,end,limit);
    if(boundary>start&&boundary<end)end=boundary;
   }
   if(end<=start)end=Math.min(start+limit,originalText.length);
   const value=originalText.slice(start,end).trim();
   if(value)chunks.push(document.createTextNode(value));
   start=end;
   while(start<originalText.length&&/\s/.test(originalText[start]))start++;
  }
  return chunks.length?chunks:[node];
 }
 const working=node.cloneNode(true);
 const media=Array.from(working.querySelectorAll('img,video'));
 media.forEach(item=>item.remove());
 const walker=document.createTreeWalker(working,NodeFilter.SHOW_TEXT);
 const textNodes=[];
 while(walker.nextNode())textNodes.push(walker.currentNode);
 const combined=textNodes.map(item=>item.nodeValue||'').join('');
 if(combined.length<=limit)return [node];
 const chunks=[];
 let start=0;
 while(start<combined.length){
  let end=Math.min(start+limit,combined.length);
  if(end<combined.length){
   const boundary=preferredSplitBoundary(combined,start,end,limit);
   if(boundary>start&&boundary<end)end=boundary;
  }
  if(end<=start)end=Math.min(start+limit,combined.length);
  let cursor=0,first=null,last=null,firstOffset=0,lastOffset=0;
  for(const textNode of textNodes){
   const size=(textNode.nodeValue||'').length;
   if(first===null&&start<cursor+size){first=textNode;firstOffset=start-cursor}
   if(end<=cursor+size){last=textNode;lastOffset=end-cursor;break}
   cursor+=size;
  }
  if(first&&last){
   const range=document.createRange();
   range.setStart(first,firstOffset);
   range.setEnd(last,lastOffset);
   const fragment=range.cloneContents();
   const clone=working.cloneNode(false);
   clone.appendChild(fragment);
   if((clone.textContent||'').trim())chunks.push(clone);
  }
  start=end;
  while(start<combined.length&&/\s/.test(combined[start]))start++;
 }
 if(!chunks.length)return [node];
 media.forEach(item=>chunks[0].appendChild(item.cloneNode(true)));
 return chunks;
}
function autoPlaceBreaks(){
 editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 const limit=messageLimit();
 const originals=Array.from(editor.childNodes);
 const output=[];
 let used=0,hasContent=false;
 for(const node of originals){
  const text=(node.innerText||node.textContent||'').trim();
  const mediaCount=node.nodeType===1?node.querySelectorAll('img,video').length:0;
  if(!text&&!mediaCount){if(output.length)output.push(node);continue}
  const chunks=splitOversizedNode(node,limit);
  for(let index=0;index<chunks.length;index++){
   const chunk=chunks[index];
   const length=(chunk.innerText||chunk.textContent||'').trim().length;
   const chunkMedia=chunk.nodeType===1?chunk.querySelectorAll('img,video').length:0;
   if(hasContent&&used+length>limit){output.push(makeBreak());used=0;hasContent=false}
   output.push(chunk);
   used+=length;
   if(length||chunkMedia)hasContent=true;
   if(index<chunks.length-1){output.push(makeBreak());used=0;hasContent=false}
  }
 }
 editor.replaceChildren(...output);
 updateSeriesStatus();
}
function insertBreakAtSelection(){
 if(!isSeriesMode())return;
 let range=savedRange?savedRange.cloneRange():null;
 const selection=window.getSelection();
 if(!range&&selection&&selection.rangeCount)range=selection.getRangeAt(0).cloneRange();
 if(range&&!(range.commonAncestorContainer===editor||editor.contains(range.commonAncestorContainer)))range=null;
 const marker=makeBreak();
 if(!range||!editor.lastChild){
  editor.appendChild(marker);
 }else{
  range.collapse(false);
  let root=range.startContainer;
  while(root&&root!==editor&&root.parentNode!==editor)root=root.parentNode;
  if(root===editor)root=null;
  try{
   const tail=document.createRange();
   if(root){
    tail.setStart(range.startContainer,range.startOffset);
    tail.setEndAfter(editor.lastChild);
    const remainder=tail.extractContents();
    editor.insertBefore(marker,root.nextSibling);
    if(remainder.childNodes.length)editor.insertBefore(remainder,marker.nextSibling);
   }else{
    const offset=range.startOffset;
    tail.setStart(editor,offset);
    tail.setEnd(editor,editor.childNodes.length);
    const remainder=tail.extractContents();
    editor.appendChild(marker);
    if(remainder.childNodes.length)editor.insertBefore(remainder,marker.nextSibling);
   }
  }catch(error){
   editor.appendChild(marker);
  }
 }
 if(selectedBreak)selectedBreak.classList.remove('selected');
 selectedBreak=null;
 updateSeriesStatus();
}
document.getElementById('insert-break').addEventListener('click',insertBreakAtSelection);
editor.addEventListener('input',()=>{updatePlainCompatibility();updateSeriesStatus()});
modeSelect.addEventListener('change',()=>{
 if(editor.querySelector('[data-local-file]')&&!['rich','rich_series','album','album_series'].includes(modeSelect.value)){
  alert('Локальные медиа поддерживаются только в рич-сообщениях и альбомах. Чтобы использовать обычный формат, замените локальные файлы публичными URL или выберите совместимый способ публикации.');
  modeSelect.value=lastModeValue;
  updateModeUI();
  return;
 }
 lastModeValue=modeSelect.value;
 seriesCheckbox.checked=modeSelect.value.endsWith('_series');
 if(modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 else editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 updateModeUI();
});
seriesCheckbox.addEventListener('change',()=>{
 if(isAlbumMode()){seriesCheckbox.checked=false;updateModeUI();return}
 if(seriesCheckbox.checked&&modeSelect.value==='plain')modeSelect.value='plain_series';
 if(seriesCheckbox.checked&&modeSelect.value==='rich')modeSelect.value='rich_series';
 if(!seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))modeSelect.value=modeSelect.value==='plain_series'?'plain':'rich';
 if(seriesCheckbox.checked&&modeSelect.value.endsWith('_series'))autoPlaceBreaks();
 else editor.querySelectorAll('.series-break').forEach(node=>node.remove());
 updateModeUI();
});
function currentResult(action){
 const series=isSeriesMode();
 const cleanEditor=document.createElement('div');
 for(const node of Array.from(editor.childNodes)){
  if(node.nodeType===1&&node.classList.contains('series-break'))continue;
  cleanEditor.appendChild(node.cloneNode(true));
 }
 return {action,html:cleanEditor.innerHTML,parts:series?htmlParts():[],profile_id:channelSelect.value||null,mode:modeSelect.value,series};
}
document.getElementById('publish').onclick=async()=>{
 if(!channelSelect.value){
  document.getElementById('status').textContent='Выберите канал (кнопка "Настроить каналы")';
  return;
 }
 const text=editor.innerText.trim();
 if(editor.querySelector('[data-local-file]')&&!['rich','rich_series','album','album_series'].includes(modeSelect.value)){
  document.getElementById('status').textContent='Локальные медиа нельзя отправить в обычном формате. Замените их публичными URL или выберите рич-сообщение либо альбом.';
  return;
 }
 if(!text&&!editor.querySelector('img,video')){
  document.getElementById('status').textContent='Добавьте текст, изображение или видео перед публикацией.';
  return;
 }
 if(!updateSeriesStatus()){
  document.getElementById('status').textContent=isAlbumMode()?'Для альбома добавьте от 2 до 10 медиа и сократите подпись до 1024 символов.':'Исправьте превышение лимита или оставьте не более одного медиа на пост перед публикацией.';
  return;
 }
 if(!confirm('Опубликовать пост в выбранном канале?'))return;
 const publishButton=document.getElementById('publish');
 publishButton.disabled=true;
 document.getElementById('status').textContent='Подготовка публикации…';
 try{await window.pywebview.api.publish(currentResult('publish'));}
 catch(error){
  publishButton.disabled=false;
  document.getElementById('status').textContent='Не удалось начать публикацию: '+(error&&error.message?error.message:String(error));
 }
};
document.getElementById('retry-pending').onclick=async()=>{
 const button=document.getElementById('retry-pending');
 button.disabled=true;
 document.getElementById('status').textContent='Подготовка повторной отправки…';
 try{await window.pywebview.api.retry_pending();}
 catch(error){
  button.disabled=false;
  document.getElementById('status').textContent='Не удалось начать повторную отправку: '+(error&&error.message?error.message:String(error));
 }
};
async function manageProfiles(){
 const status=document.getElementById('status');
 try{
  const profiles=await window.pywebview.api.get_profiles();
  const action=prompt('Управление каналами:\n1 — добавить канал\n2 — изменить канал\n3 — удалить канал\nОтмена — закрыть');
  if(action===null)return;
  if(action==='1'){
   const name=prompt('Название канала:');
   if(name===null)return;
   const chatId=prompt('Идентификатор канала (@имя или числовой ID):');
   if(chatId===null)return;
   const token=prompt('Токен бота:');
   if(token===null)return;
   config.profiles=await window.pywebview.api.save_channel_profile(name,chatId,token,null);
   config.selected_profile_id=config.profiles[config.profiles.length-1]?.profile_id||null;
  }else if(action==='2'||action==='3'){
   if(!profiles.length){status.textContent='Сначала добавьте канал.';return;}
   const list=profiles.map((p,i)=>(i+1)+' — '+p.name+' ('+p.chat_id+')').join('\n');
   const choice=prompt('Введите номер канала:\n'+list);
   if(choice===null)return;
   const index=Number(choice)-1;
   if(!Number.isInteger(index)||index<0||index>=profiles.length){status.textContent='Неверный номер канала.';return;}
   const profile=profiles[index];
   if(action==='3'){
    if(!confirm('Удалить канал «'+profile.name+'»?'))return;
    config.profiles=await window.pywebview.api.delete_channel_profile(profile.profile_id);
    config.selected_profile_id=config.profiles[0]?.profile_id||null;
   }else{
    const name=prompt('Название канала:',profile.name);
    if(name===null)return;
    const chatId=prompt('Идентификатор канала:',profile.chat_id);
    if(chatId===null)return;
    const token=prompt('Новый токен (оставьте пустым, чтобы сохранить прежний):');
    if(token===null)return;
    config.profiles=await window.pywebview.api.save_channel_profile(name,chatId,token,profile.profile_id);
    config.selected_profile_id=profile.profile_id;
   }
  }else{
   status.textContent='Выберите 1, 2 или 3.';
   return;
  }
  channelSelect.replaceChildren();
  for(const profile of config.profiles){
   const option=document.createElement('option');
   option.value=profile.profile_id;
   option.textContent=profile.name+' — '+profile.chat_id;
   channelSelect.append(option);
  }
  if(config.selected_profile_id)channelSelect.value=config.selected_profile_id;
  status.textContent=config.profiles.length?'Список каналов обновлён.':'Каналы не настроены.';
 }catch(error){
  status.textContent='Не удалось изменить список каналов: '+(error&&error.message?error.message:String(error));
 }
}
document.getElementById('manage').onclick=manageProfiles;
let statusPolling=false;
async function pollEditorStatus(){
 if(statusPolling||!window.pywebview||!window.pywebview.api)return;
 statusPolling=true;
 try{
  const update=await window.pywebview.api.get_status();
  if(update){
   if(Array.isArray(update.profiles)){
    config.profiles=update.profiles;
    channelSelect.replaceChildren();
    for(const profile of update.profiles){
     const option=document.createElement('option');
     option.value=profile.profile_id;
     option.textContent=profile.name+' — '+profile.chat_id;
     channelSelect.append(option);
    }
    channelSelect.value=update.selected_profile_id||'';
    if(!channelSelect.value&&channelSelect.options.length)channelSelect.selectedIndex=0;
   }
   const retryButton=document.getElementById('retry-pending');
   retryButton.hidden=!update.can_retry;
   const sending=Boolean(update.message&&(update.message.startsWith('Отправка')||update.message.startsWith('Повторная отправка')));
   retryButton.disabled=sending;
   document.getElementById('publish').disabled=sending;
   if(update.message){
    document.getElementById('status').textContent=update.message;
    if(!sending)retryButton.disabled=false;
   }
  }
 }catch(error){}
 finally{statusPolling=false;}
}
setInterval(pollEditorStatus,500);
window.applyEditorConfig=applyConfig;
</script>
</body></html>"""


MANUAL_HTML = r"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Руководство — Telegram Publisher</title>
<style>body{font:16px "Segoe UI",sans-serif;line-height:1.55;color:#222;background:#f4f5f7;margin:0;padding:24px}article{max-width:760px;margin:0 auto;background:#fff;padding:28px 34px;border-radius:8px;box-shadow:0 1px 5px #0001}h1{margin-top:0}h2{margin-top:1.5em;font-size:1.2em}a{color:#1558a6}li{margin:.35em 0}.meta{color:#555}</style>
</head><body><article>
<h1>Руководство по Telegram Publisher</h1>
<p class="meta"><b>Версия:</b> {{VERSION}}<br><b>Дата сборки:</b> 25.10.2026<br><b>Автор:</b> Анкап-тян</p>
<p>Сайт: <a href="https://ancapchan.info" target="_blank" rel="noreferrer">https://ancapchan.info</a><br>Telegram-канал: <a href="https://t.me/ancapchan" target="_blank" rel="noreferrer">https://t.me/ancapchan</a></p><p>Донаты: <a href="https://ancapchan.info/donate" target="_blank" rel="noreferrer">https://ancapchan.info/donate</a></p>
<h2>Задача приложения</h2>
<p>Telegram Publisher — это инструмент для подготовки и публикации сообщений в каналах Telegram. Можно настроить несколько каналов и выбирать, какие публикации отправлять в каждый из них. Доступны обычные и рич-сообщения, а также публикация текста серией сообщений.</p>
<h2>Импорт и черновики</h2>
<p>Пост можно создавать непосредственно в редакторе, вставить из буфера обмена, загрузить из файла или импортировать с веб-страницы по URL. Поддерживаются форматы TXT, HTML, Markdown, DOCX и ODT. Черновик можно сохранить в файл <code>.draft</code>, а затем открыть для дальнейшего редактирования.</p>
<ul><li><b>Импортировать по ссылке</b> — загрузить публикацию со страницы по URL.</li><li><b>Открыть файл</b> — импортировать TXT, HTML, Markdown, DOCX или ODT либо восстановить черновик .draft.</li><li><b>Сохранить черновик</b> — сохранить форматирование, режим публикации, выбранный канал и положение разрывов для серии постов в файле .draft.</li></ul>
<h2>Подготовка публикации</h2>
<p>Основная область окна — визуальный редактор. Панель инструментов позволяет применять форматирование, создавать списки, заголовки, цитаты, ссылки и таблицы. Кнопка «Медиа по URL» добавляет изображение или видео по публичной ссылке. В зависимости от выбранного способа публикации доступны разные инструменты редактирования. Если выбранный способ публикации не поддерживает отдельные элементы оформления, приложение преобразует их в доступный формат.</p>
<h2>Выбор способа публикации</h2>
<p>Обычные сообщения поддерживают базовое форматирование: жирный шрифт, курсив, подчёркивание, зачёркивание, гиперссылки и цитаты. Для прикрепления одного изображения или видео используется скрытая ссылка, которую Telegram преобразует в предпросмотр. Максимальная длина сообщения — 4096 символов. Локальные медиа в обычном формате не поддерживаются: используйте публичный URL или выберите рич-сообщение либо альбом.</p>
<p>Рич-сообщения позволяют более сложное форматирование. Для длинных публикаций можно выбрать серию сообщений. Режим «Альбом» отправляет от 2 до 10 изображений и видео с общей подписью длиной до 1024 символов. «Серия альбомов» позволяет создать несколько альбомов; каждый блок между разрывами становится отдельным альбомом со своей подписью и должен содержать от 2 до 10 медиа. Для альбомов можно использовать прямые публичные URL или кнопку «Медиа из файла».</p>
<p>В режиме серии кнопка «Разрыв сообщения» вставляет границу в текущем месте. Разрыв можно выбрать и удалить. Перед публикацией проверяйте предупреждения о длине текста и количестве медиа.</p>
<h2>Настройка каналов</h2>
<p>В нижней части окна нажмите «Настроить каналы…», чтобы добавить один или несколько профилей. Для каждого профиля укажите название, идентификатор канала и токен бота, которому разрешено публиковать сообщения в этом канале. Публикации отправляются от имени бота.</p>
<h2>Публикация</h2>
<p>Перед публикацией проверьте итоговый вид поста непосредственно в визуальном редакторе и нажмите «Опубликовать». Для всех способов публикации приложение запрашивает подтверждение. Строка состояния внизу редактора показывает ход работы и результат.</p>
<hr>
<h2>История версий</h2>
<ul><li><b>1.1.0</b> — добавлена публикация альбомов.</li><li><b>1.0.0</b> — базовый функционал приложения: визуальный редактор, импорт публикаций, черновики, профили каналов, обычные и рич-сообщения и их серии.</li></ul>
</article></body></html>""".replace("{{VERSION}}", __version__)

class EditorApi:
    """Обеспечить работу визуального редактора и публикацию сообщений."""

    def __init__(self, window: object) -> None:
        self.window = window
        self.manual_window = None
        self._status_lock = threading.Lock()
        self._status_update: dict | None = None
        self._publishing = False
        self._pending_profile: ChannelProfile | None = None
        self._pending_messages: list[str] = []
        self._pending_sent_count = 0
        self._pending_retry_after = 0.0

    @staticmethod
    def _public_profile(profile: ChannelProfile) -> dict[str, str]:
        """Вернуть настройки канала без секретного токена."""
        return {
            "profile_id": profile.profile_id,
            "name": profile.name,
            "chat_id": profile.chat_id,
        }

    def get_profiles(self) -> list[dict[str, str]]:
        """Получить список каналов без раскрытия токенов ботов."""
        return [self._public_profile(profile) for profile in load_profiles()]

    def save_channel_profile(
        self, name: str, chat_id: str, token: str = "", profile_id: str | None = None
    ) -> list[dict[str, str]]:
        """Создать или обновить канал; при редактировании пустой токен сохраняется прежним."""
        if profile_id and not token.strip():
            existing = next(
                (profile for profile in load_profiles() if profile.profile_id == profile_id),
                None,
            )
            if existing is None or not existing.token:
                raise ValueError("Для этого канала нужно указать токен бота.")
            token = existing.token
        save_profile(name, token, chat_id, profile_id)
        return self.get_profiles()

    def delete_channel_profile(self, profile_id: str) -> list[dict[str, str]]:
        """Удалить выбранный канал и вернуть актуальный список."""
        if not profile_id:
            raise ValueError("Не выбран канал для удаления.")
        delete_profile(profile_id)
        return self.get_profiles()

    def publish(self, result: dict) -> None:
        """Опубликовать сообщение выбранным способом прямо из визуального редактора."""
        mode = str(result.get("mode", "rich"))
        if mode not in {"plain", "plain_series", "rich", "rich_series", "album", "album_series", "media_text"}:
            raise ValueError("Неизвестный способ публикации.")
        if self._publishing:
            raise ValueError("Публикация уже выполняется.")
        profile_id = result.get("profile_id")
        profile = next((item for item in load_profiles() if item.profile_id == profile_id), None)
        if profile is None or not profile.token or not profile.chat_id:
            raise ValueError("Настройки выбранного канала не заполнены. Проверьте профиль и токен.")
        content = str(result.get("html", "")).strip()
        raw_parts = result.get("parts")
        parts = [str(part) for part in raw_parts] if isinstance(raw_parts, list) else None
        if not content and not parts:
            raise ValueError("Добавьте текст, изображение или видео перед публикацией.")
        request = PublicationRequest(profile, content, None, mode, bool(result.get("series", False)), parts)
        self._publishing = True
        self._set_status("Отправка публикации…")

        self._pending_profile = profile
        self._pending_messages = []
        self._pending_sent_count = 0
        self._pending_retry_after = 0.0
        self._start_publication(request)

    def retry_pending(self) -> None:
        """Повторить отправку оставшихся сообщений после ограничения Telegram."""
        if self._publishing:
            raise ValueError("Публикация уже выполняется.")
        if self._pending_profile is None or not self._pending_messages:
            raise ValueError("Нет сообщений, ожидающих повторной отправки.")
        request = PublicationRequest(
            profile=self._pending_profile,
            content=self._pending_messages[0],
            image_path=None,
            mode="plain_prepared",
            series=True,
            parts=list(self._pending_messages),
            initial_delay=max(1.0, self._pending_retry_after + 1.0),
        )
        self._start_publication(request, retry=True)

    def _start_publication(self, request: PublicationRequest, retry: bool = False) -> None:
        """Выполнить запрос в фоне и сохранить состояние частичной отправки."""
        self._publishing = True
        self._set_status(
            "Повторная отправка оставшихся сообщений…" if retry else "Отправка публикации…"
        )

        def run_publication() -> None:
            try:
                count = PublicationController().publish(request)
            except PartialPublicationError as error:
                if retry:
                    self._pending_sent_count += error.sent_count
                else:
                    self._pending_sent_count = error.sent_count
                self._pending_messages = list(error.pending_messages)
                self._pending_retry_after = max(1.0, float(error.retry_after))
                self._set_status(
                    f"Часть публикации отправлена: {self._pending_sent_count}. Осталось сообщений: "
                    f"{len(self._pending_messages)}. Повторить можно через "
                    f"{int(self._pending_retry_after + 0.999)} сек.",
                    can_retry=True,
                )
            except Exception as error:
                self._set_status(f"Ошибка публикации: {error}")
            else:
                total_sent = self._pending_sent_count + count if retry else count
                self._pending_messages = []
                self._pending_profile = None
                self._pending_sent_count = 0
                self._pending_retry_after = 0.0
                self._set_status(f"Опубликовано. Отправлено сообщений: {total_sent}")
            finally:
                self._publishing = False

        threading.Thread(target=run_publication, daemon=True).start()

    def _set_status(self, message: str, can_retry: bool = False) -> None:
        """Сохранить однократное уведомление для редактора."""
        with self._status_lock:
            payload = {"message": message}
            if can_retry:
                payload["can_retry"] = True
            self._status_update = payload

    def get_status(self) -> dict | None:
        """Получить однократное уведомление о публикации."""
        with self._status_lock:
            payload = self._status_update
            self._status_update = None
            return payload

    def import_url(self, url: str) -> str:
        """Загрузить публикацию по URL и вернуть HTML для редактора."""
        return import_from_url(url)

    def open_file(self) -> dict | None:
        """Открыть документ для импорта или восстановить черновик редактора."""
        paths = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Поддерживаемые форматы (*.draft;*.txt;*.html;*.htm;*.md;*.markdown;*.docx;*.odt)",
                "Черновик Telegram Publisher (*.draft)",
                "Текстовые файлы (*.txt)",
                "HTML (*.html;*.htm)",
                "Markdown (*.md;*.markdown)",
                "Документы Word (*.docx)",
                "Документы OpenDocument (*.odt)",
            ),
        )
        if not paths:
            return None
        path = Path(paths[0])
        if path.suffix.lower() == ".draft":
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"Не удалось прочитать файл черновика: {error}") from error
            return {"type": "draft", "draft": draft}
        return {"type": "content", "html": import_from_file(path)}

    def open_manual(self) -> None:
        """Открыть отдельное окно руководства, не закрывая редактор."""
        if self.manual_window is not None:
            try:
                self.manual_window.show()
                self.manual_window.restore()
                return
            except Exception:
                self.manual_window = None
        manual = webview.create_window(
            "Руководство — Telegram Publisher", html=MANUAL_HTML,
            width=780, height=780, resizable=True,
        )
        self.manual_window = manual
        manual.events.closed += lambda *_args: setattr(self, "manual_window", None)

    def save_draft(self, draft: dict, filename: str = "Черновик") -> str | None:
        """Сохранить полное состояние редактора в файл .draft."""
        if not isinstance(draft, dict):
            raise ValueError("Не удалось получить данные черновика.")
        if (
            draft.get("format") != "telegram-publisher-draft"
            or draft.get("version") != 1
            or not isinstance(draft.get("html"), str)
            or draft.get("mode") not in {"rich", "plain", "rich_series", "plain_series", "album", "album_series"}
            or not isinstance(draft.get("series"), bool)
            or (draft.get("profile_id") is not None and not isinstance(draft.get("profile_id"), str))
        ):
            raise ValueError("Редактор передал некорректные данные черновика.")
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(filename))
        safe_name = re.sub(r"\s+", " ", safe_name).strip(" .")[:100] or "Черновик"
        path = self.window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=f"{safe_name}.draft",
            file_types=("Черновики Telegram Publisher (*.draft)",),
        )
        if not path:
            return None
        if isinstance(path, (list, tuple)):
            path = path[0] if path else None
        if not path:
            return None
        destination = Path(path)
        if destination.suffix.lower() != ".draft":
            destination = destination.with_suffix(".draft")
        destination.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(destination)

    def select_media_files(self) -> list[dict[str, str]]:
        """Выбрать локальные изображения и видео для совместимых способов публикации."""
        paths = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=(
                "Изображения и видео (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.avif;*.mp4;*.m4v;*.mov;*.webm;*.mkv)",
                "Изображения (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.avif)",
                "Видео (*.mp4;*.m4v;*.mov;*.webm;*.mkv)",
                "Все файлы (*.*)",
            ),
        )
        if not paths:
            return []
        if isinstance(paths, (str, Path)):
            paths = [paths]
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"}
        video_extensions = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
        selected: list[dict[str, str]] = []
        for item in paths:
            path = Path(item).resolve()
            suffix = path.suffix.lower()
            if suffix not in image_extensions | video_extensions:
                raise ValueError(
                    f"Формат файла «{path.name}» не поддерживается. "
                    "Выберите изображение или видео из списка форматов."
                )
            if not path.is_file():
                continue
            selected.append(
                {
                    "path": str(path),
                    "uri": f"data:{mimetypes.guess_type(path.name)[0] or 'application/octet-stream'};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}",
                    "type": "video" if suffix in video_extensions else "photo",
                }
            )
        return selected

    def import_file(self) -> str | None:
        """Предложить выбрать локальный файл и преобразовать его в HTML."""
        paths = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Поддерживаемые документы (*.txt;*.html;*.htm;*.md;*.markdown;*.docx;*.odt)",
                "Текстовые файлы (*.txt)",
                "HTML (*.html;*.htm)",
                "Markdown (*.md;*.markdown)",
                "Документы Word (*.docx)",
                "Документы OpenDocument (*.odt)",
            ),
        )
        if not paths:
            return None
        return import_from_file(Path(paths[0]))


def main() -> None:
    """Запустить визуальный редактор как главное окно приложения."""
    profiles = load_profiles()
    initial_content = ""
    config = {
        "profiles": [EditorApi._public_profile(profile) for profile in profiles],
        "selected_profile_id": profiles[0].profile_id if profiles else None,
        "mode": "rich",
        "series": False,
        "status": "Выберите канал и подготовьте публикацию.",
    }

    window = webview.create_window(
        "Telegram Publisher — редактор",
        html=EDITOR_HTML,
        width=1200,
        height=850,
    )
    api = EditorApi(window)
    window.expose(api.publish, api.retry_pending, api.get_status, api.import_url, api.import_file, api.open_file, api.save_draft, api.open_manual, api.select_media_files, api.get_profiles, api.save_channel_profile, api.delete_channel_profile)

    def initialize() -> None:
        window.evaluate_js(
            "window.initialContent = "
            + json.dumps(initial_content, ensure_ascii=False)
            + "; window.applyEditorConfig("
            + json.dumps(config, ensure_ascii=False)
            + ");"
        )

    window.events.loaded += initialize
    webview.start(debug=False)


if __name__ == "__main__":
    main()
