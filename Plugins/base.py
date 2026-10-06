import ipaddress, asyncio, time, json, re
from timeit import default_timer as timer
from pathlib import Path
import shutil
import importlib.util

class Base():

    def __init__(self,config=None):
        self.config = config or {}

    def load(self,config=None):
        with (Path(__file__).resolve().parents[1] / 'mapping.json').open(encoding='utf-8') as f:
            self.map = json.load(f)

    def find(self,target,field):
        for row in self.map:
            if target.casefold() == row[field].casefold(): return row

    def start(self):
        self.timer = timer()

    def diff(self):
        return round((timer() - self.timer),2)

    def isComparable(self):
        return False

    def canRunAny(self):
        return False

    def compare(self,countries,param):
        origin, target = countries.split(',')
        originData = self.engage(origin,"1.1.1.1")
        return originData

    def run(self, data):
        try:
            myClass = getattr(importlib.import_module(f"Plugins.{data['plugin']}"), data['plugin'])
            instance = myClass(self.config)
            instance.regions = data.get('regions', [])
            if data['target'] == 'compare' and not instance.isComparable():
                return {}
            if data['origin'] == 'any' and not instance.canRunAny():
                return {}
            if instance.prepare() is not True:
                print(f"{data['plugin']} failed to prepare")
                return {}
            if data['target'] == 'compare':
                return instance.compare(data['origin'], data['target'])
            return instance.engage(data['origin'], data['target'])
        except Exception as exc:
            print(f"{data['plugin']} failed: {type(exc).__name__}: {exc}")
            return {}

    def GetAlpha2(self, target):
        if not isinstance(target, str):
            return False
        target = {'UK': 'GB', 'UAE': 'ARE', 'USA': 'USA'}.get(target.upper(), target)
        if not hasattr(self, 'map'):
            self.load()
        field = 'alpha-2' if len(target) == 2 else 'alpha-3' if len(target) == 3 else 'name'
        result = self.find(target, field)
        return result['alpha-2'] if result else False

    def getCountry(self, target):
        code = self.GetAlpha2(target)
        result = self.find(code, 'alpha-2') if code else None
        return result['name'] if result else False

    def validateIP(self,address):
        try:
            ip = ipaddress.ip_address(address)
            return True
        except (ValueError, TypeError):
            return False

    async def launchBrowser(self):
        from pyppeteer import launch
        configured = self.config.get('executablePath')
        executable = (shutil.which(configured) if configured else None)
        if not configured:
            executable = next((shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable') if shutil.which(name)), None)
        if not executable:
            raise RuntimeError('Chromium not found. Install Chromium or set executablePath in config.json.')
        return await launch(headless=True, executablePath=executable,
                            args=self.config.get('browserArgs', []),
                            handleSIGINT=False, handleSIGTERM=False, handleSIGHUP=False)

    async def browse(self, target, wait=10, element=""):
        browser = await self.launchBrowser()
        try:
            last_error = None
            for run in range(4):
                page = await browser.newPage()
                try:
                    await page.goto(target, {'waitUntil': 'domcontentloaded', 'timeout': self.config.get('timeout', 30000)})
                    if wait == 0:
                        await page.waitForSelector(element, {'timeout': self.config.get('timeout', 30000)})
                    else:
                        await asyncio.sleep(wait)
                    return await page.content()
                except Exception as exc:
                    last_error = exc
                finally:
                    await page.close()
            raise RuntimeError(f'Could not load {target}: {last_error}') from last_error
        finally:
            await browser.close()

    def browseWrapper(self, target, wait=10, element=""):
        # browse() already retries failed navigation; avoid multiplying retries.
        return asyncio.run(self.browse(target, wait, element))

    def formatTable(self,list):
        longest,response = {},""
        for row in list:
            elements = row.split("\t")
            for index, entry in enumerate(elements):
                if not index in longest: longest[index] = 0
                if len(entry) > longest[index]: longest[index] = len(entry)
        for i, row in enumerate(list):
            elements = row.split("\t")
            for index, entry in enumerate(elements):
                if len(entry) < longest[index]:
                    diff = longest[index] - len(entry)
                    while len(entry) < longest[index]:
                        entry += " "
                response += f"{entry}" if response.endswith("\n") or response == "" else f" {entry}"
            if i < len(list) -1: response += "\n"
        return response
