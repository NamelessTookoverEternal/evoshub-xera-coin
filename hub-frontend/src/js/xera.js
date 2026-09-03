const API=window.XERA_API_BASE||((location.hostname==='localhost'||location.hostname==='127.0.0.1')?'http://localhost:8000':'https://api.evoshub.xyz');
const $=id=>document.getElementById(id);
let mining=null;
const token=()=>localStorage.getItem('xera_evos_token')||'';
const fmt=n=>Number(n||0).toLocaleString('en-US',{
    maximumFractionDigits:2
}
);
async function req(path,opts={
}
){
    const r=await fetch(API+path,{
        ...opts,headers:{
            'Content-Type':'application/json',Authorization:`Bearer ${token()}`,...(opts.headers||{
            }
            )
        }
    }
    );
    const d=await r.json().catch(()=>({
    }
    ));
    if(!r.ok)throw new Error(d.detail||'Request failed');
    return d
}
async function login(e){
    e.preventDefault();
    $('loginError').textContent='';
    try{
        const d=await req('/api/xera/auth/login',{
            method:'POST',body:JSON.stringify({
                identifier:$('identifier').value,password:$('password').value
            }
            )
        }
        );
        localStorage.setItem('xera_evos_token',d.token);
        localStorage.setItem('xera_evos_user',JSON.stringify(d.user));
        await load()
    }
    catch(err){
        $('loginError').textContent=err.message
    }
}
async function load(){
    try{
        const [w,m,t]=await Promise.all([req('/api/xera/wallet'),req('/api/xera/mining/status'),req('/api/xera/transactions?limit=20&offset=0')]);
        $('loginView').hidden=true;
        $('walletView').hidden=false;
        $('balance').textContent=fmt(w.balance);
        $('walletStatus').textContent=w.wallet_status||'ACTIVE';
        mining=m.mining;
        renderMining();
        const list=t.transactions||[];
        $('transactions').innerHTML=list.length?list.map(x=>`<div class="tx"><span><b>${x.type.replaceAll('_',' ')}</b><br><small>${new Date(x.created_at).toLocaleString()}</small></span><span class="${x.direction==='CREDIT'?'credit':''}">${x.direction==='CREDIT'?'+':'-'}${fmt(x.amount)} XERA<br><small>${x.status}</small></span></div>`).join(''):'<p class="muted">No transactions yet.</p>'
    }
    catch(err){
        localStorage.removeItem('xera_evos_token');
        $('walletView').hidden=true;
        $('loginView').hidden=false;
        $('loginError').textContent='Please sign in again.'
    }
}
function renderMining(){
    const b=$('miningAction');
    if(!mining){
        $('miningLabel').textContent='MINING READY';
        $('countdown').textContent='Start your 24-hour session';
        $('rewardText').textContent='The server controls the mining timer.';
        b.textContent='START MINING';
        return
    }
    const remain=new Date(mining.expires_at)-Date.now();
    if(remain<=0){
        $('miningLabel').textContent='MINING COMPLETE';
        $('countdown').textContent=`+${fmt(mining.estimated_reward)} XERA READY`;
        $('rewardText').textContent='Your session is complete and ready for server verification.';
        b.textContent='CLAIM XERA'
    }
    else{
        const s=Math.floor(remain/1000),h=String(Math.floor(s/3600)).padStart(2,'0'),m=String(Math.floor(s%3600/60)).padStart(2,'0'),sec=String(s%60).padStart(2,'0');
        $('miningLabel').textContent='MINING ACTIVE';
        $('countdown').textContent=`${h}:${m}:${sec}`;
        $('rewardText').textContent=`+${fmt(mining.estimated_reward)} XERA estimated for this session`;
        b.textContent='MINING ACTIVE';
        b.disabled=true
    }
}
$('loginForm').addEventListener('submit',login);
$('logout').onclick=()=>{
    localStorage.removeItem('xera_evos_token');
    location.reload()
}
;
$('miningAction').onclick=async()=>{
    const b=$('miningAction');
    b.disabled=true;
    try{
        if(!mining){
            const d=await req('/api/xera/mining/start',{
                method:'POST',body:'{}'
            }
            );
            mining=d.mining
        }
        else{
            await req('/api/xera/mining/claim',{
                method:'POST',body:JSON.stringify({
                    session_id:mining.id
                }
                )
            }
            );
            mining=null;
            await load()
        }
        renderMining()
    }
    catch(e){
        $('error').textContent=e.message
    }
    finally{
        if(mining&&new Date(mining.expires_at)>Date.now()){
        }
        else b.disabled=false
    }
}
;
setInterval(()=>{
    if(mining)renderMining()
}
,1000);
if(token())load();
