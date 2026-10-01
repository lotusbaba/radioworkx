"""Closed-action Playwright adapter shared by both engines and replay."""
import asyncio
from urllib.parse import urljoin, urlsplit

from adversary.models.action import (ActionType, CandidateAction, ClickAction, DoneAction,
    ElementLocator, FillAction, KeyPressAction, LocatorAlternative, LocatorKind,
    NavigateAction, ReloadAction, ScrollAction, SelectAction, TargetAction, WaitAction)
from adversary.models.observation import BrowserElement, BrowserObservation
from .recording import fingerprint


class ActionPolicy:
    def __init__(self, origin):
        parsed = urlsplit(origin)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.port in (None, 8000, 8001):
            raise ValueError('Only a harness-created disposable loopback target is supported')
        self.origin = origin.rstrip('/')

    def allows(self, url):
        parsed = urlsplit(url)
        expected = urlsplit(self.origin)
        return (parsed.scheme, parsed.hostname, parsed.port) == (expected.scheme, expected.hostname, expected.port) and not parsed.username and not parsed.password

    def resolve(self, url):
        value = urljoin(self.origin + '/', url)
        if not self.allows(value):
            raise ValueError('Action leaves the QA origin')
        return value


# This is fixed harness code, never model-generated JavaScript.
SNAPSHOT = r'''() => {
 const path = el => {
   if(el.id && document.querySelectorAll('#'+CSS.escape(el.id)).length===1) return '#'+CSS.escape(el.id);
   const parts=[];
   while(el && el.nodeType===1) {
     let p=el.tagName.toLowerCase();
     const peers=el.parentElement ? [...el.parentElement.children].filter(x=>x.tagName===el.tagName) : [el];
     p+=':nth-of-type('+(peers.indexOf(el)+1)+')';parts.unshift(p);el=el.parentElement;
   } return parts.join(' > ');
 };
 const root=document.querySelector('dialog[open]') || document;
 return [...root.querySelectorAll('a[href],button,input:not([type=hidden]),textarea,select,[role=button]')]
 .filter(el=>el.checkVisibility() && !el.closest('[inert]')).slice(0,100).map(el=>({
 selector:path(el),tag:el.tagName.toLowerCase(), type:el.type||'', disabled:!!el.disabled,
 options:el.tagName==='SELECT'?[...el.options].filter(o=>!o.disabled && !o.parentElement.disabled).map(o=>({value:o.value,label:o.label})):[],
 name:(el.getAttribute('aria-label')||el.labels?.[0]?.innerText||el.innerText||el.placeholder||'').slice(0,512)
 }));
}'''


class BrowserAdapter:
    def __init__(self, page, origin, session_id, recorder, max_actions=20):
        self.page, self.policy, self.session_id, self.recorder = page, ActionPolicy(origin), session_id, recorder
        self.max_actions = max_actions
        self.step = 0
        self.observation = None
        self.raw = []
        self.findings = []
        self.handles = {}
        self.done = False
        self.observation_number = 0

    async def attach(self):
        context = self.page.context
        async def route_request(route):
            if self.policy.allows(route.request.url):
                await route.continue_()
            else:
                await route.abort()
        async def close_socket(socket):
            await socket.close()
        await context.route('**/*', route_request)
        await context.route_web_socket('**/*', close_socket)
        await context.add_init_script("document.addEventListener('DOMContentLoaded',()=>document.querySelectorAll('audio').forEach(a=>a.muted=true))")
        def register(page):
            page.on('pageerror', lambda error: self.find('pageerror', str(error)))
            page.on('crash', lambda _: self.find('crash', 'page crashed'))
            page.on('dialog', lambda dialog: dialog.dismiss())
            page.on('download', lambda download: download.cancel())
            if page != self.page:
                # Popup navigation requests are also covered by context routing.
                page.on('domcontentloaded', lambda: page.close())
        register(self.page)
        context.on('page', register)
        context.on('response', lambda response: self.find('http_5xx', f'{response.status} {urlsplit(response.url).path}')
                   if response.status >= 500 and self.policy.allows(response.url) else None)
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)

    def find(self, kind, message):
        item = {'type': kind, 'message': message[:2048], 'fingerprint': fingerprint(kind, message[:2048])}
        if item not in self.findings:
            self.findings.append(item)
            self.recorder.write('finding', **item)

    async def observe(self):
        for handle in self.handles.values():
            await handle.dispose()
        self.handles = {}
        self.raw = await self.page.evaluate(SNAPSHOT)
        oid = f'{self.session_id}-obs-{self.observation_number}'
        self.observation_number += 1
        elements = []
        for index, item in enumerate(self.raw):
            eid = f'e{index}'
            locator = ElementLocator(observation_id=oid, element_id=eid,
                alternatives=(LocatorAlternative(kind=LocatorKind.CSS, value=item['selector']),))
            elements.append(BrowserElement(locator=locator, role=item['tag'], accessible_name=item['name'], disabled=item['disabled']))
            self.handles[eid] = await self.page.locator(item['selector']).element_handle()
        self.observation = BrowserObservation(id=oid, session_id=self.session_id, step=self.step,
            url=self.page.url, title=(await self.page.title())[:512],
            visible_text=(await self.page.locator('body').inner_text())[:16384], elements=tuple(elements))
        self.recorder.write('observation', observation=self.observation.model_dump(mode='json'))
        return self.observation

    def candidates(self, values):
        result = []
        for element, item in zip(self.observation.elements, self.raw):
            if element.disabled:
                continue
            if item['tag'] in ('input', 'textarea') and item['type'] not in ('checkbox', 'radio', 'submit', 'button', 'file'):
                bindings = getattr(self, 'input_bindings', None)
                assigned = (values if bindings is None else
                            (bindings[element.accessible_name],) if element.accessible_name in bindings else ())
                for value in assigned:
                    result.append(CandidateAction(id=f'a{len(result)}', description=f'Fill {element.accessible_name}: {value!r}'[:512],
                                                 action=FillAction(target=element.locator, value=value)))
                result.append(CandidateAction(id=f'a{len(result)}', description=f'Press Enter in {element.accessible_name}'[:512],
                                             action=KeyPressAction(target=element.locator, key='Enter')))
            elif item['tag'] == 'select':
                for option in item.get('options', []):
                    result.append(CandidateAction(id=f'a{len(result)}',
                        description=f'Select {option["label"]} in {element.accessible_name}'[:512],
                        action=SelectAction(target=element.locator, values=(option['value'],))))
            elif item['type'] != 'file':
                result.append(CandidateAction(id=f'a{len(result)}', description=f'Click {element.accessible_name}'[:512],
                                             action=ClickAction(target=element.locator)))
        for description, action in [('Reload', ReloadAction()), ('Wait for UI', WaitAction(duration_ms=500)),
                                    ('Scroll down', ScrollAction(delta_y=600)), ('Finish exploration', DoneAction(reason='Agent finished'))]:
            result.append(CandidateAction(id=f'a{len(result)}', description=description, action=action))
        return tuple(result[:496] + result[-4:]) if len(result) > 500 else tuple(result)

    async def execute(self, action, replay=False):
        if self.done or self.step >= self.max_actions:
            raise RuntimeError('Action budget exhausted or session already finished')
        if action.type == ActionType.NAVIGATE:
            self.policy.resolve(action.url)
        if isinstance(action, TargetAction) and not replay:
            if not self.observation or action.target.observation_id != self.observation.id:
                raise ValueError('Stale observation')
            if action.target not in tuple(e.locator for e in self.observation.elements):
                raise ValueError('Unknown target')
            handle = self.handles.get(action.target.element_id)
            if handle is None or not await handle.evaluate('(el)=>el.isConnected'):
                raise ValueError('Target detached; observe again')
        self.recorder.write('intent', step=self.step, action=action.model_dump(mode='json'))
        self.step += 1
        try:
            async with asyncio.timeout(action.timeout_ms / 1000):
                await self._execute(action, replay)
            self.recorder.write('result', step=self.step - 1, status='ok')
        except Exception as error:
            self.recorder.write('result', step=self.step - 1, status='error', error_type=type(error).__name__)
            raise

    async def _execute(self, action, replay):
        target = None
        if isinstance(action, TargetAction):
            if replay:
                for alternative in action.target.alternatives:
                    if alternative.kind == LocatorKind.CSS:
                        locator = self.page.locator(alternative.value)
                    elif alternative.kind == LocatorKind.TEST_ID:
                        locator = self.page.get_by_test_id(alternative.value)
                    elif alternative.kind == LocatorKind.ROLE:
                        locator = self.page.get_by_role(alternative.value, name=alternative.accessible_name, exact=alternative.exact)
                    elif alternative.kind == LocatorKind.LABEL:
                        locator = self.page.get_by_label(alternative.value, exact=alternative.exact)
                    else:
                        locator = self.page.get_by_text(alternative.value, exact=alternative.exact)
                    if await locator.count() == 1:
                        target = locator
                        break
                if target is None:
                    raise ValueError('Replay target missing or ambiguous')
            else:
                target = self.handles[action.target.element_id]
        kind = action.type
        if kind == ActionType.NAVIGATE:
            await self.page.goto(self.policy.resolve(action.url), wait_until='domcontentloaded')
        elif kind == ActionType.CLICK:
            await target.click(timeout=action.timeout_ms)
        elif kind == ActionType.FILL:
            await target.fill(action.value, timeout=action.timeout_ms)
        elif kind == ActionType.SELECT:
            await target.select_option(list(action.values), timeout=action.timeout_ms)
        elif kind == ActionType.HOVER:
            await target.hover(timeout=action.timeout_ms)
        elif kind in (ActionType.KEY_PRESS, ActionType.SUBMIT):
            await target.press(action.key if kind == ActionType.KEY_PRESS else 'Enter', timeout=action.timeout_ms)
        elif kind == ActionType.SCROLL:
            await self.page.mouse.wheel(action.delta_x, action.delta_y)
        elif kind == ActionType.RELOAD:
            await self.page.reload(wait_until='domcontentloaded')
        elif kind == ActionType.BACK:
            await self.page.go_back(wait_until='domcontentloaded')
        elif kind == ActionType.FORWARD:
            await self.page.go_forward(wait_until='domcontentloaded')
        elif kind == ActionType.WAIT:
            await asyncio.sleep(action.duration_ms / 1000)
        elif kind == ActionType.DONE:
            self.done = True
        else:
            raise ValueError('Unsupported action')
        if self.page.url != 'about:blank' and not self.policy.allows(self.page.url):
            raise ValueError('Browser left the QA origin')
