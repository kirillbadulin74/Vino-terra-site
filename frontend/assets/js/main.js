/* ВИНОТЕРРА — общий скрипт */
(function(){
  "use strict";
  var W = window.WINE || {};

  /* ---------- утилиты ---------- */
  function el(tag, cls, html){var e=document.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;return e;}
  function esc(s){return (s==null?"":String(s)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c];});}
  /* безопасный Markdown-рендер ответов ассистента: **жирный**, ###заголовки, списки */
  function assistantMarkdown(source){
    var text=String(source||"").replace(/\r\n?/g,"\n").replace(/\b(1[0-9]{3}|20[0-9]{2})(1[0-9]{3}|20[0-9]{2})\b/g,"$1–$2");
    function inline(value){return esc(value).replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");}
    var out=[],inList=false;
    text.split("\n").forEach(function(raw){
      var line=raw.trim().replace(/[ \t]{2,}/g," — "),heading=line.match(/^#{1,4}\s+(.+)$/),bullet=line.match(/^[-*•]\s+(.+)$/);
      if(bullet){if(!inList){out.push("<ul>");inList=true;}out.push("<li>"+inline(bullet[1])+"</li>");return;}
      if(inList){out.push("</ul>");inList=false;}
      if(!line)return;
      if(heading){out.push("<h4>"+inline(heading[1])+"</h4>");return;}
      out.push("<p>"+inline(line)+"</p>");
    });
    if(inList)out.push("</ul>");
    return out.join("");
  }
  function chips(arr, cls){
    if(!arr||!arr.length) return "";
    return '<div class="chips">'+arr.map(function(g){return '<span class="chip '+(cls||"")+'">'+esc(g)+'</span>';}).join("")+'</div>';
  }

  /* ---------- мобильное меню ---------- */
  function initNav(){
    var b=document.querySelector(".burger"), links=document.querySelector(".nav-links");
    if(b&&links){
      b.addEventListener("click",function(){b.classList.toggle("open");links.classList.toggle("open");});
      links.querySelectorAll("a").forEach(function(a){a.addEventListener("click",function(){b.classList.remove("open");links.classList.remove("open");});});
    }
  }

  /* ---------- ассистент: fab + чат на сайте (Telegram — альтернатива) ---------- */
  var TG_BOT="https://t.me/VinoTerra_AI_bot";
  function initAssistant(){
    if(document.querySelector(".fab")) return;
    var bot = (document.body.getAttribute("data-img")||"assets/img/")+"assistant_bot.jpg";
    var fab=el("button","fab");
    fab.innerHTML='<span class="dot"></span><img src="'+bot+'" alt="Нейро-сомелье"><span class="fab-txt"><b>Нейро-сомелье</b><small>Спросить о вине</small></span>';
    document.body.appendChild(fab);

    var modal=el("div","modal");
    modal.innerHTML=''+
      '<div class="modal-bg"></div>'+
      '<div class="modal-card chat-card" role="dialog" aria-modal="true" aria-labelledby="chat-title">'+
        '<button class="modal-close" aria-label="Закрыть">✕</button>'+
        '<div class="chat-head"><img src="'+bot+'" alt=""><div><span class="badge-live">● Онлайн</span><h3 id="chat-title">Нейро-сомелье</h3><p>Отвечает по базе знаний ВИНОТЕРРЫ. Удобнее в мессенджере? <a class="tg-link" href="'+TG_BOT+'" target="_blank" rel="noopener">Он же в Telegram</a>.</p></div></div>'+
        '<div class="chat-log" aria-live="polite"><div class="chat-msg bot-msg">Здравствуйте! Спросите меня о вине, сортах, регионах или сочетаниях с едой.</div></div>'+
        '<form class="chat-form"><label class="sr-only" for="sommelier-question">Ваш вопрос</label><textarea id="sommelier-question" maxlength="1200" rows="2" placeholder="Например: чем известен Мальбек?" required></textarea><button class="btn btn-primary" type="submit">Отправить</button></form>'+
        '<p class="chat-note">ИИ может ошибаться. 18+ · Наслаждайтесь вкусом, знайте меру.</p>'+
      '</div>';
    document.body.appendChild(modal);

    var form=modal.querySelector(".chat-form"), input=form.querySelector("textarea"), log=modal.querySelector(".chat-log"), submit=form.querySelector("button[type=submit]");
    var chatHistory=[];
    var isLocal=/^(localhost|127\.0\.0\.1)$/.test(location.hostname)||location.protocol==="file:";
    /* пустой apiBase = тот же домен (nginx проксирует /api); локально — dev-API на :8080 */
    var apiBase=(window.VINOTERRA_API_URL||(isLocal?"http://127.0.0.1:8080":"")).replace(/\/$/,"");
    function addMessage(text,cls){var msg=el("div","chat-msg "+cls);msg.textContent=text;log.appendChild(msg);log.scrollTop=log.scrollHeight;return msg;}
    function addFeedback(interactionId){
      if(!interactionId)return;
      var box=el("div","chat-feedback");
      box.innerHTML='<span>Ответ помог?</span><button type="button" data-vote="up" aria-label="Полезный ответ">👍</button><button type="button" data-vote="down" aria-label="Неудачный ответ">👎</button>';
      box.querySelectorAll("button").forEach(function(b){
        b.addEventListener("click",function(){
          box.querySelectorAll("button").forEach(function(x){x.disabled=true;});
          b.classList.add("voted");
          fetch(apiBase+"/api/feedback",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({interaction_id:interactionId,vote:b.getAttribute("data-vote")})}).catch(function(){});
          box.querySelector("span").textContent="Спасибо за оценку!";
        });
      });
      log.appendChild(box);log.scrollTop=log.scrollHeight;
    }
    function open(){modal.classList.add("open");setTimeout(function(){input.focus();},50);}
    function close(){modal.classList.remove("open");}
    fab.addEventListener("click",open);
    modal.querySelector(".modal-bg").addEventListener("click",close);
    modal.querySelector(".modal-close").addEventListener("click",close);
    document.addEventListener("keydown",function(e){if(e.key==="Escape")close();});
    document.querySelectorAll("[data-open-assistant]").forEach(function(n){n.addEventListener("click",function(e){e.preventDefault();open();});});
    input.addEventListener("keydown",function(e){if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
    form.addEventListener("submit",function(e){
      e.preventDefault();
      var question=input.value.trim(); if(!question||submit.disabled)return;
      addMessage(question,"user-msg"); input.value=""; submit.disabled=true;
      var pending=addMessage("Подбираю ответ…","bot-msg pending");
      fetch(apiBase+"/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:question,history:chatHistory.slice(-6)})})
        .then(function(response){return response.json().catch(function(){return {};}).then(function(body){if(!response.ok)throw new Error(body.detail&&typeof body.detail==="string"?body.detail:"Сервис временно недоступен");return body;});})
        .then(function(body){var answer=body.answer||"Ответ не получен.";pending.classList.remove("pending");pending.classList.add("markdown");pending.innerHTML=assistantMarkdown(answer);chatHistory.push({role:"user",content:question},{role:"assistant",content:answer});chatHistory=chatHistory.slice(-6);addFeedback(body.interaction_id);})
        .catch(function(error){pending.classList.remove("pending");pending.classList.add("error-msg");pending.textContent=error.message||"Не удалось связаться с помощником.";})
        .finally(function(){submit.disabled=false;input.focus();});
    });
  }

  /* ---------- scroll reveal (с защитой от невидимого контента) ---------- */
  function revealAll(){document.querySelectorAll(".reveal").forEach(function(n){n.classList.add("in");});}
  function initReveal(){
    if(!("IntersectionObserver" in window)){revealAll();return;}
    var io=new IntersectionObserver(function(es){
      es.forEach(function(en){if(en.isIntersecting){en.target.classList.add("in");io.unobserve(en.target);}});
    },{threshold:.08,rootMargin:"0px 0px -5% 0px"});
    document.querySelectorAll(".reveal:not(.in)").forEach(function(n){io.observe(n);});
    // подстраховка: если что-то осталось скрытым (ошибка IO/вкладка в фоне) — показать через 2.2с
    setTimeout(revealAll,2200);
  }

  /* ---------- аккордеоны ---------- */
  function initAcc(){
    document.querySelectorAll(".acc-head").forEach(function(h){
      h.addEventListener("click",function(){h.parentElement.classList.toggle("open");});
    });
  }

  /* ---------- карточка страны/региона ---------- */
  function placeCard(item, imgBase, imgKey, flagBase){
    var img = imgBase ? (imgBase+(imgKey||item.id)+".jpg") : null;
    var flagFallback = item.emoji ? ' onerror="this.outerHTML=\''+item.emoji+' \'"' : ' onerror="this.style.display=\'none\'"';
    var flag = flagBase ? '<img class="flag" src="'+flagBase+(imgKey||item.id)+'.svg" alt="" loading="lazy"'+flagFallback+'>' : (item.emoji?item.emoji+' ':'');
    var facts = (item.facts||[]).map(function(f){return '<li>'+esc(f)+'</li>';}).join("");
    var c=el("article","card reveal");
    c.setAttribute("data-name",(item.name||"").toLowerCase());
    c.setAttribute("data-search",((item.name||"")+" "+(item.grapes||[]).join(" ")+" "+(item.signature||"")+" "+(item.buy||"")).toLowerCase());
    if(item.continent) c.setAttribute("data-cont",item.continent);
    c.innerHTML =
      (img?'<img class="card-img" loading="lazy" src="'+img+'" alt="'+esc(item.name)+'" onerror="this.style.display=\'none\'">':'')+
      '<div class="card-body">'+
        '<h3>'+flag+esc(item.name)+'</h3>'+
        (item.tagline?'<div class="tagline">'+esc(item.tagline)+'</div>':'')+
        (facts?'<ul style="margin:6px 0 0;padding-left:18px;color:var(--ink-soft);font-size:.94rem;display:flex;flex-direction:column;gap:5px">'+facts+'</ul>':'')+
        (item.signature?'<p style="margin-top:8px"><b style="color:var(--red)">✦ Чем знаменит:</b> '+esc(item.signature)+'</p>':'')+
        (item.buy?'<p><b style="color:var(--terracotta)">🛒 Купить и попробовать:</b> '+esc(item.buy)+'</p>':'')+
        (item.tourism?'<p><b style="color:var(--amber-deep)">📍 Туристу:</b> '+esc(item.tourism)+'</p>':'')+
        chips(item.grapes)+
      '</div>';
    return c;
  }

  /* ---------- рендер сетки с фильтром/поиском ---------- */
  function renderGrid(opts){
    var host=document.getElementById(opts.host); if(!host) return;
    opts.items.forEach(function(it){host.appendChild(placeCard(it,opts.imgBase,opts.imgKey,opts.flagBase));});
    var search=opts.searchId?document.getElementById(opts.searchId):null;
    var empty=opts.emptyId?document.getElementById(opts.emptyId):null;
    var filterCont="all";
    function apply(){
      var q=search?search.value.trim().toLowerCase():"";
      var shown=0;
      host.querySelectorAll(".card").forEach(function(c){
        var okC = filterCont==="all" || c.getAttribute("data-cont")===filterCont;
        var okQ = !q || c.getAttribute("data-search").indexOf(q)>-1;
        var vis = okC&&okQ; c.style.display=vis?"":"none"; if(vis)shown++;
      });
      if(empty) empty.style.display=shown?"none":"block";
    }
    if(search) search.addEventListener("input",apply);
    if(opts.filterBarId){
      var bar=document.getElementById(opts.filterBarId);
      if(bar) bar.querySelectorAll(".filter-btn").forEach(function(btn){
        btn.addEventListener("click",function(){
          bar.querySelectorAll(".filter-btn").forEach(function(b){b.classList.remove("active");});
          btn.classList.add("active"); filterCont=btn.getAttribute("data-cont")||"all"; apply();
        });
      });
    }
    initReveal();
  }

  /* экспорт для страниц */
  window.VT = {el:el, esc:esc, chips:chips, placeCard:placeCard, renderGrid:renderGrid, initReveal:initReveal, data:W};

  document.addEventListener("DOMContentLoaded",function(){
    initNav(); initAssistant(); initAcc(); initReveal();
  });
})();
