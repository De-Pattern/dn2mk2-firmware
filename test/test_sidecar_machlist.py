"""Native machine-list construction, frozen identity and input boundaries.

Runs stock row creation/navigation plus compiled adapter; heap and external UI
owner access are substituted. No device, boot loop or audio-engine rebuild.
"""
import struct
import pytest
from .test_sidecar_capture import capture
from .test_sidecar_pages import compiled_runtime
from .test_sidecar_ui import ui_server, SIDECAR
import subprocess
from dnfw.sidecar import machines as sc
from unicorn import m68k_const as reg
import unicorn as U


@pytest.fixture
def native_list(capture, compiled_runtime):
    feed,*_=capture
    cpu,call=feed.cpu,feed.call
    stock,built=compiled_runtime
    for base,size in ((0x40000000,0x400000),(0x40580000,0x80000),(0x42430000,0x10000),
                      (0x46700000,0x10000),(0x47000000,0x200000)):
        cpu.mem_map(base,size)
    cpu.mem_write(0x40000400,built['content'])
    for name in ('chunk','machines_chunk'):
        cpu.mem_write(built[name]['load'],built[name]['code'])
    def put(at,*values):cpu.mem_write(at,struct.pack('>'+str(len(values))+'I',*values))
    def get(at):return struct.unpack('>I',cpu.mem_read(at,4))[0]
    sound=0x46a09001;put(0x800052a0,sound-52)
    screen,node,view,item,packet=0x46a05000,0x46a05100,0x46a05200,0x46a05600,0x46a06000
    put(built['layout']['wr_screen_obj'],screen);put(screen+28,node);put(node+8,view)
    put(view,0x401df9d8);put(view+432,6);put(view+132,0x46a08020)
    cpu.mem_write(0x42431a6c,b'\0');put(0x4058e8d4,200)
    heap=0x47000000;allocations={};freed=[];commits=[];machine_commits=[];rendered_labels=[]
    def ret(value=0):
        sp=cpu.reg_read(reg.UC_M68K_REG_A7);pc=get(sp)
        cpu.reg_write(reg.UC_M68K_REG_D0,value);cpu.reg_write(reg.UC_M68K_REG_A7,sp+4);cpu.reg_write(reg.UC_M68K_REG_PC,pc)
    def stub(_,at,size,user):
        nonlocal heap
        sp=cpu.reg_read(reg.UC_M68K_REG_A7)
        if at==0x40120264:
            n=get(sp+4);address=heap;heap+=(n+15)&~15;assert heap<0x47200000
            allocations[address]=n;ret(address)
        elif at==0x40120270:freed.append(get(sp+4));ret()
        elif at==0x4003134e:ret(cpu.mem_read(sound+1163*get(sp+8)+0xde,1)[0])
        elif at==built['layout']['sc_select']:
            commits.append((get(sp+4),bytes(cpu.mem_read(get(sp+8)+8,32))))
            put(built['layout']['sc_edit_mask'],0);ret(1)
        elif at==built['layout']['smp_machine_commit']:
            if get(sp+12)>=256:ret();return
            track=get(sp+8)
            assert get(built['layout']['sc_edit_mask'])==1<<track
            machine_commits.append(get(sp+12));cpu.mem_write(sound+1163*track+0xde,bytes([sc.TYPE]));ret(1)
        elif at==0x4015103c:
            rendered_labels.append(bytes(cpu.mem_read(get(sp+12),16)).split(b'\0')[0]);ret()
        else:ret()
    for at in (0x40120264,0x40120270,0x40046bfe,0x40030e66,0x4003134e,
               0x4011c7ba,0x4015103c,built['layout']['sc_select'],built['layout']['smp_machine_commit']):
        cpu.hook_add(U.UC_HOOK_CODE,stub,begin=at,end=at)
    token,now=12345,200
    def catalog(entries,revision=1):
        call('sc_catalog_open',1)
        for i,(ident,name) in enumerate(entries or [('', '')]):
            assert call('sc_catalog_request',token,now,packet)==50
            req=bytes(cpu.mem_read(packet,50));reply=bytearray(71)
            reply[:14]=req[:14];reply[5]=4;reply[14]=2;reply[15]=i
            reply[21]=revision;reply[22]=len(entries);reply[23]=1 if entries else 0
            reply[24:56]=ident.encode().ljust(32,b'\0');reply[56:66]=name.encode().ljust(10,b'\0')
            reply[66:70]=name[:4].encode().ljust(4,b'\0');reply[70]=0xf7
            cpu.mem_write(packet,bytes(reply));assert call('sc_catalog_receive',packet,71,now)==1
        assert call('sc_catalog_publish')==1
    def rawcall(address,*args):
        key='native_test_call';built['layout'][key]=address
        return call(key,*args)
    # Stock vector getter's already-initialized master types (no guard/atexit).
    put(0x405ccfb0,0x46a07000,0x46a07018,0x46a07018);cpu.mem_write(0x405ccfc4,b'\x01')
    put(0x46a07000,0,2,1,3,sc.TYPE,4)
    def build():rawcall(0x4005b2c0,view)
    def values():
        begin,end=get(view+388),get(view+392)
        return [get(get(p)+4) for p in range(begin,end,8)]
    def row(value):
        put(view+420,values().index(value));put(view+424,0)
        assert rawcall(0x4005b162,view)==value
    def event(code,flags=1,kind=0,function=0):
        raw=bytearray(12);raw[0]=kind;struct.pack_into('>II',raw,4,code,flags)
        cpu.mem_write(item,bytes(raw));return call('sc_pick_pop',item,function)
    def text(at):return bytes(cpu.mem_read(at,32)).split(b'\0')[0]
    return locals()


def test_stock_machine_list_rows_names_current_and_frozen_catalog(native_list):
    n=native_list;call=n['call'];n['cpu'].mem_write(n['sound']+0xde,b'\0')
    n['catalog']([('demo.bell','BELL'),('demo.tone','TONE')]);n['build']()
    values=n['values']();assert [v for v in values if v!=0xffffffff]==[0,2,1,3,256,257,4]
    assert n['text'](call('sc_list_name',256))==b'BELL'
    assert n['text'](call('sc_list_name',257))==b'TONE'
    assert n['text'](call('sc_list_name',0))==b'FM Tone'
    # Execute the stock label callback through the installed call-site patch.
    n['row'](256)
    entry=n['get'](n['get'](n['view']+388)+8*n['values']().index(256))
    n['cpu'].reg_write(reg.UC_M68K_REG_A0,n['packet'])
    n['rawcall'](0x4005a874,n['view'],entry)
    assert n['rendered_labels']==[b'BELL']
    for site in (0x4005b6c2,0x4005a9c8,0x4005a5c6,0x4005a632):
        assert bytes(n['cpu'].mem_read(site,6))==b'\x4e\xb9'+struct.pack('>I',n['built']['layout']['sc_list_current'])
    # Native source/filter scrolling uses real MenuEntry objects.
    n['row'](257);n['rawcall'](0x4005a956,n['view'])
    ident=n['packet'];n['cpu'].mem_write(ident,b'demo.tone'.ljust(32,b'\0'))
    n['cpu'].mem_write(n['sound']+0xde,bytes([sc.TYPE]))
    assert call('sc_sound_store',n['sound'],ident)==1
    assert call('sc_list_current',0,0)==257
    n['catalog']([('demo.tone','TONE'),('demo.bell','BELL')],2)
    assert n['text'](call('sc_list_name',256))==b'BELL'
    assert call('sc_list_current',0,0)==257
    n['build']();assert n['text'](call('sc_list_name',256))==b'TONE'
    assert call('sc_list_current',0,0)==256
    n['cpu'].mem_write(0x42431a6c,b'\x08');n['build']()
    assert all(x<256 or x==0xffffffff for x in n['values']())
    assert n['freed']


def test_native_yes_requests_load_only_and_no_private_shortcut(native_list):
    n=native_list;call=n['call'];n['catalog']([('demo.bell','BELL')]);n['build']();n['row'](256)
    before=bytes(n['cpu'].mem_read(n['sound'],1163))
    assert n['event'](10)==1 and call('sc_pick_target')
    assert bytes(n['cpu'].mem_read(n['sound'],1163))==before and not n['commits']
    assert n['event'](10,9)==1 and n['event'](10,0)==1
    assert n['text'](call('sc_list_label',256))==b'LOADING'
    # Browsing away cancels pending intent, preserving stock navigation.
    n['row'](0);call('sc_pick_poll');assert call('sc_pick_target')==0
    assert n['event'](10)==0
    n['put'](n['view'],0x401d49a8) # SYN rather than MACHINE SEL
    assert n['event'](10,function=1)==0 and call('sc_pick_visible')==0
    assert call('smp_machine_commit',0,0,256,1,1)==0
    assert bytes(n['cpu'].mem_read(n['sound'],1163))==before


@pytest.mark.parametrize('load_state,descriptor_state',[(1,1),(5,0)])
@pytest.mark.parametrize('source_type',[sc.TYPE,1])
@pytest.mark.parametrize('track',range(8))
def test_native_confirm_waits_for_matching_metadata(native_list,ui_server,tmp_path,load_state,descriptor_state,source_type,track):
    n=native_list;call=n['call'];cpu=n['cpu'];packet=n['packet'];exe,opts=ui_server
    n['catalog']([('demo.bell','BELL')]);n['build']()
    # Reuse the stock window built on track 1, as on the physical DN2.
    sound=n['sound']+1163*track
    cpu.mem_write(sound+0xde,bytes([source_type]))
    cpu.mem_write(0x42431a6c,bytes([track]));call('sc_pick_poll');n['row'](256)
    before=bytes(cpu.mem_read(sound,1163))
    assert n['event'](10)==1
    def exchange(name):
        count=call(name+'_request',n['token'],n['now'],packet)
        if not count:return False
        request=bytes(cpu.mem_read(packet,count));a,r=tmp_path/'ask.bin',tmp_path/'reply.bin';a.write_bytes(request)
        subprocess.run([str(exe),'--answer',str(a),str(r),str(SIDECAR/'build/dn2/fixtures/bell.rmp')],**opts)
        reply=bytearray(r.read_bytes())
        if name=='sc_load':reply[22]=load_state
        elif request[14:17]==bytes(3):reply[22]=descriptor_state
        cpu.mem_write(packet,bytes(reply));assert call(name+'_receive',packet,len(reply),n['now'])==1
        return True
    assert exchange('sc_load');assert n['event'](10)==1 and not n['commits']
    for _ in range(20):
        call('sc_ui_follow')
        if not exchange('sc_ui'):break
    call('sc_ui_follow');call('sc_pick_poll')
    assert bytes(cpu.mem_read(sound,1163))==before
    assert n['text'](call('sc_list_label',256))==(b'YES:USE' if load_state==1 else b'YES:SWAP')
    assert n['event'](10)==1
    assert n['commits']==[(track,b'demo.bell'.ljust(32,b'\0'))]
    assert n['machine_commits']==([] if source_type==sc.TYPE else [sc.TYPE])
    assert n['get'](n['built']['layout']['sc_edit_mask'])==0
    assert call('sc_pick_target')==0


def test_native_list_catalog_arrival_and_project_cancellation(native_list):
    n=native_list;call=n['call'];n['build']()
    assert 256 not in n['values']()
    n['catalog']([('demo.bell','BELL')]);call('sc_pick_poll')
    assert 256 in n['values']()
    n['row'](256);assert n['event'](10)==1
    n['put'](n['built']['layout']['smp_pj_loads'],1);call('sc_pick_poll')
    assert call('sc_pick_target')==0 and not n['commits']
    # The reused window is rebound to the new project; another YES must start
    # a fresh request, never confirm the previous project's pending choice.
    n['row'](256);assert n['event'](10)==1 and not n['commits']
    assert n['text'](call('sc_list_label',256))==b'LOADING'


def test_closed_list_stops_catalog_and_encoders_skip_picker_work(native_list):
    n=native_list;call=n['call'];cpu=n['cpu'];packet=n['packet']
    cpu.mem_write(n['sound']+0xde,b'\0')
    n['build']();call('sc_pick_poll')
    assert call('sc_catalog_request',n['token'],200,packet)==50
    n['catalog']([('demo.bell','BELL')]);call('sc_pick_poll')
    assert 256 in n['values']() and sc.TYPE not in n['values']()
    # Closing cancels scanning, but keeps the published list for immediate reopen.
    n['put'](n['view'],0x401d49a8);call('sc_pick_poll')
    assert call('sc_catalog_request',n['token'],2000,packet)==0
    assert call('sc_catalog_view')
    visited=[]
    def visit(_,at,size,user):visited.append(at)
    handles=[cpu.hook_add(U.UC_HOOK_CODE,visit,begin=n['built']['layout'][fn],
                         end=n['built']['layout'][fn])
             for fn in ('sc_pick_poll','sc_catalog_publish','sc_catalog_open')]
    for _ in range(64):assert n['event'](1,kind=1)==0
    assert not visited
    for h in handles:cpu.hook_del(h)
    n['put'](n['view'],0x401df9d8);n['build']()
    assert 256 in n['values']()
    call('sc_pick_poll');assert call('sc_catalog_request',n['token'],2000,packet)==50


def test_missing_saved_engine_retains_fallback(native_list):
    n=native_list;call=n['call'];n['cpu'].mem_write(n['sound']+0xde,bytes([sc.TYPE]))
    n['build']();assert sc.TYPE in n['values']()
    n['catalog']([('demo.bell','BELL')]);n['build']()
    assert sc.TYPE in n['values']() # legacy Perkons is not in this catalog
    n['cpu'].mem_write(n['packet'],b'demo.bell'.ljust(32,b'\0'))
    assert call('sc_sound_store',n['sound'],n['packet'])==1
    n['build']();assert sc.TYPE not in n['values']()
    assert call('sc_list_current',0,0)==256


def test_live_catalog_refresh_preserves_identity_and_blocks_stale_yes(native_list):
    n=native_list;call=n['call']
    n['catalog']([('public.a','ALPHA'),('public.b','BETA')]);n['build']();call('sc_pick_poll');n['row'](257)
    n['catalog']([('public.b','BETA'),('public.c','GAMMA'),('public.a','ALPHA')],2)
    # YES queued against the former mapping only refreshes; it cannot select a different engine.
    assert n['event'](10)==1 and not call('sc_pick_target') and not n['commits']
    assert n['rawcall'](0x4005b162,n['view'])==256
    assert n['text'](call('sc_list_name',256))==b'BETA'
    assert n['text'](call('sc_list_name',257))==b'GAMMA'
    n['catalog']([('public.c','GAMMA')],3);call('sc_pick_poll')
    assert n['text'](call('sc_list_name',256))==b'GAMMA'
    n['catalog']([],4);call('sc_pick_poll')
    assert all(x<256 or x==0xffffffff for x in n['values']())
    allocations=len(n['allocations']);call('sc_pick_poll');call('sc_pick_poll')
    assert len(n['allocations'])==allocations # empty catalogs do not rebuild forever


@pytest.mark.parametrize('engine,parameter', [('md',8),('juno',0),('fm',0)])
def test_contextual_metadata_follows_sound_without_mutating_it(native_list,engine,parameter):
    """Compiled UI follows base controls; delayed model/track replies are discarded.

    Replies model a metadata server here; C++ protocol interoperability is covered
    separately. No listening or project filesystem round-trip claim.
    """
    n=native_list;cpu=n['cpu'];call=n['call'];packet=n['packet'];now=200
    ident=('sidecar.builtin.'+engine).encode().ljust(32,b'\0')
    for track,selector in ((0,0),(7,127)):
        sound=n['sound']+1163*track
        cpu.mem_write(packet,ident);assert call('sc_sound_store',sound,packet)==1
        for k,(_,slot) in enumerate(sc.ALL_RECORDS):
            cpu.mem_write(sound+20+2*slot,struct.pack('>H',((selector if k==parameter else k+1)<<8)|0x55))
    originals=[bytes(cpu.mem_read(n['sound']+1163*t,1163)) for t in range(8)]

    def ask():
        count=call('sc_ui_request',n['token'],now,packet)
        return bytes(cpu.mem_read(packet,count))

    def reply(request):
        track,selector=request[17:19]
        data=bytearray(request[:17]);data[5]=4
        revision=1+track*128+selector
        data+=bytes((revision>>s)&127 for s in (28,21,14,7,0))
        if request[15]==0:
            data+=bytes((1,1 if engine=='md' else 5,16,5))
            data+=engine.upper().encode().ljust(10,b'\0')+engine.upper().encode().ljust(4,b'\0')
            data+=f'PATCH {selector}'.encode().ljust(13,b'\0')
            data+=bytes(2) # existing metadata fingerprint fields
        else:
            for k in range((request[15]-1)*4,request[15]*4):
                data+=bytes((k+1,0,0,0,0,127,64,0))
                visible=k<8 or (engine=='md' and k==8)
                data+=(f'M{selector} P{k+1}'.encode() if visible else b'').ljust(12,b'\0')
                data+=(f'P{k+1}'.encode() if visible else b'').ljust(4,b'\0')
        return bytes(data)+b'\xf7'

    def receive(data):
        cpu.mem_write(packet,data);return call('sc_ui_receive',packet,len(data),now)

    call('sc_ui_follow');old=ask();assert old[17:19]==bytes((0,0))
    cpu.mem_write(0x42431a6c,b'\x07');call('sc_ui_follow')
    assert receive(reply(old))==0 and call('sc_ui_view')==0
    for track,selector in ((7,127),(0,0)):
        cpu.mem_write(0x42431a6c,bytes((track,)));call('sc_ui_follow')
        assert call('sc_ui_view')==0
        for part in range(5):
            request=ask()
            assert len(request)==52 and request[4]==3 and request[17:19]==bytes((track,selector))
            assert request[19:51]==ident and request[14:17]==bytes((0,part,0))
            assert receive(reply(old))==0
            assert receive(reply(request))==1
            assert call('sc_ui_publish')==(part==4)
        call('sc_ui_follow');assert call('sc_ui_view')
        assert n['text'](call('sc_ui_label',0,0))==f'M{selector} P1'.encode()
        page=call('sc_ui_page',0)
        assert n['text'](n['get'](page+4))==(b'' if engine=='md' else f'PATCH {selector}'.encode())
        # The native SYN header copies these as old-ABI std::strings, not C text.
        # Execute the real stock copy/destructor; only allocation is substituted.
        for page_index in (0,1):
            descriptor=call('sc_ui_page',page_index)
            for field in (0,4):
                source=n['get'](descriptor+field);expected=n['text'](source)
                destination=packet+512
                n['rawcall'](0x401cdd94,destination,descriptor+field)
                copied=n['get'](destination)
                assert copied!=source, 'native string copy must never share a static page buffer'
                assert n['get'](copied-12)==len(expected) and n['text'](copied)==expected
                assert n['get'](source-4)==0xffffffff
                # Rebuilding either page must not mutate a header already owned by the UI.
                call('sc_ui_page',1-page_index)
                assert n['text'](copied)==expected
                n['rawcall'](0x401ccbee,destination)
                assert n['freed'][-1]==copied-12 and copied-12 in n['allocations']
        assert n['rawcall'](0x400c24d2,sc.TYPE)==(2 if engine=='md' else 1)
        if engine!='md':
            # A remembered page-2 index is redirected immediately, not a blank grid.
            first=bytes(cpu.mem_read(page,44))
            assert bytes(cpu.mem_read(call('sc_ui_page',1),44))==first
            # Run the real single-page SYN heading builder (hidden string return
            # in A0), then its real destructor. Only view/model getters are stubs.
            def model_getter(_,at,size,user):
                n['ret'](1 if at==0x4004b7f2 else 0xffffffff)
            hooks=[cpu.hook_add(U.UC_HOOK_CODE,model_getter,begin=at,end=at)
                   for at in (0x4004b7f2,0x400167a4)]
            for stale_index in (0,1,0,1):
                n['put'](n['view']+144,stale_index)
                cpu.reg_write(reg.UC_M68K_REG_A0,destination)
                n['rawcall'](0x400177b2,n['view'])
                copied=n['get'](destination)
                assert n['text'](copied)==f'PATCH {selector}'.encode()
                n['rawcall'](0x401ccbee,destination)
                assert n['freed'][-1]==copied-12 and copied-12 in n['allocations']
            for h in hooks:cpu.hook_del(h)
        # Ordinary control changes do not request a new descriptor or hide labels.
        sound=n['sound']+1163*track;slot=sc.ALL_RECORDS[1][1]
        prior=bytes(cpu.mem_read(sound+20+2*slot,2));cpu.mem_write(sound+20+2*slot,b'\x7e\x01')
        call('sc_ui_follow');assert call('sc_ui_view') and ask()==b''
        cpu.mem_write(sound+20+2*slot,prior)
        now+=1
    assert [bytes(cpu.mem_read(n['sound']+1163*t,1163)) for t in range(8)]==originals
