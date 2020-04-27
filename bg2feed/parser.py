# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import functools
import json
import os
from urllib import parse
import time

import bs4
import requests
from flask import request
from selenium import webdriver


class GlobeParser(object):
    def __init__(self):
        print('Initializing...')
        self.driver_options = webdriver.ChromeOptions()
        self.driver_options.add_argument('headless')
        driver = webdriver.Chrome(options=self.driver_options)

        self.login(driver)
        self.cookies = driver.get_cookies()
        driver.close()

        self.session = requests.session()
        for cookie in self.cookies:
            c = requests.cookies.create_cookie(
                domain=cookie['domain'], name=cookie['name'], value=cookie['value']
            )
            self.session.cookies.set_cookie(c)

        print('Logged in! Ready.')

    def get_driver(self) -> webdriver.Chrome:
        driver = webdriver.Chrome(options=self.driver_options)
        driver.get('https://www.bostonglobe.com')
        for cookie in self.cookies:
            if 'expiry' in cookie:
                del(cookie['expiry'])
            driver.add_cookie(cookie)
        return driver

    @staticmethod
    def login(driver):
        driver.get('https://pages.bostonglobe.com/login/')

        email_field = driver.find_element_by_name('email')
        email_field.send_keys(os.environ['BOSTONGLOBE_USER'])

        pass_field = driver.find_element_by_name('password')
        pass_field.send_keys(os.environ['BOSTONGLOBE_PASS'])

        submit = driver.find_element_by_xpath('/html/body/div/div/section/form/input')
        submit.click()

        time.sleep(10)

    @staticmethod
    def replace_url(url):
        if 'bostonglobe.com' not in url:
            # These links are served by www3 and start with /
            url = 'https://www3.bostonglobe.com%s' % url
        original_encoded = parse.quote(url)
        return '%s/proxy/%s' % (request.url_root, original_encoded)

    @staticmethod
    def restore_url(url):
        url = url.replace('%s/proxy/' % request.url_root, '')
        return parse.unquote(url)

    @staticmethod
    def parse_title(soup) -> str:
        return soup.title.text.replace(' - The Boston Globe', '')

    @staticmethod
    def fix_image_url(url: str):
        # Images hosted in this domain are (so far) prepended
        # by a resizer script. Go straight to the source.
        index = url.find('arc-anglerfish')
        if index > -1:
            url = url[index:]

        if url.startswith('//'):
            url = 'https:%s' % url
        if not url.startswith('https://'):
            url = 'https://%s' % url

        return url

    @staticmethod
    def parse_metadata(soup) -> dict:
        # TODO(knikolla): There are still cases where author doesn't show up.
        try:
            metadata = json.loads(soup.find('script', type='application/ld+json').text)
        except AttributeError:
            return {'author': 'BostonGlobe.com'}

        try:
            authors = metadata['author']['name']
            if isinstance(authors, list):
                authors = ', '.join(authors)
            metadata['author'] = authors
        except KeyError:
            metadata['author'] = 'BostonGlobe.com'
        return metadata

    @classmethod
    def parse_images(cls, soup) -> list:
        images = []

        query = soup.find_all('img', 'width_full')
        for image in query:
            images.append({'src': cls.fix_image_url(image['data-src']),
                           'alt': image['alt']})

        query = soup.find_all('img', 'lead-media__media')
        for image in query:
            images.append({'src': cls.fix_image_url(image['src']),
                           'alt': image['alt']})
        return images

    @staticmethod
    def parse_article_from_script(soup) -> list:
        scripts = soup.find_all('script')
        messy_json = None
        for script in scripts:
            if 'Fusion.globalContent' in script.text:
                messy_json = script.text
        if not messy_json:
            print('Error finding article data!')
            return ['Error loading article.']
        start = messy_json.find('{"_id":')
        messy_json = messy_json[start:]
        end = messy_json.find(';Fusion.globalContentConfig')
        script = messy_json[:end]
        inside = False
        clean_json = ''
        for i, char in enumerate(script):
            if char == '<':
                inside = True
            if char == '>':
                inside = False
            if inside and char == '"':
                char = '\"'  # Unescaped characters prevent json loading
            clean_json = clean_json + char
        article = json.loads(clean_json)
        return [
            x['content'] for x in article['content_elements'] if x['type'] == 'text'
        ]

    @property
    def today_url(self):
        now = datetime.datetime.now()
        today = now.strftime('%Y/%m/%d')
        return 'https://www3.bostonglobe.com/todayspaper/%s' % today

    def find_top_stories(self):
        html = self.session.get(self.today_url).text
        soup = bs4.BeautifulSoup(html, 'html5lib')

        # Top Stories
        top = soup.find('div', 'stories-top')
        top = top.find_all('div', 'story')

        top_stories = []
        for story in top:
            processed = {
                'title': story.find('h2').text,
                'url': self.replace_url(story.find('a')['href']),
                'summary': ''.join([p.text for p in story.find_all('p')])
            }
            image = story.find('img')
            if image:
                processed['image'] = self.fix_image_url(image['src'])

            top_stories.append(processed)
        return top_stories

    def find_section(self, key):
        html = self.session.get(self.today_url).text
        soup = bs4.BeautifulSoup(html, 'html5lib')
        sections = soup.find_all('div', 'tod-paper-section')
        found = None
        for section in sections:
            title = section.find('h2').find('a').text
            if key in title.lower():
                found = section
                break

        if not found:
            return

        stories = []
        parsed = section.find_all('a')[1:]
        for story in parsed:
            try:
                stories.append({'title': story.find('h3').text,
                                'url': self.replace_url(story['href'])})
            except AttributeError:
                # Because of course, in some the A is inside the H3
                continue

        parsed = section.find_all('h3')[1:]
        for story in parsed:
            try:
                stories.append({'title': story.text,
                                'url': self.replace_url(story.find('a')['href'])})
            except (AttributeError, TypeError):
                # Because of course, in some the A is inside the H3
                continue
        return stories

    def get_section(self, section):
        html = self.session.get('https://www3.bostonglobe.com/news/%s' % section).text

        soup = bs4.BeautifulSoup(html, 'html5lib')
        section = soup.find_all('div', 'stories-top')[0]
        stories = []

        parsed = section.find_all('div', 'story')
        for story in parsed:
            a = story.find('a')
            stories.append({'title': a.text,
                            'url': self.replace_url(a['href'])})
        return stories

    @functools.lru_cache(maxsize=128)
    def get_article_selenium(self, url):
        driver = self.get_driver()
        driver.get(url)
        soup = bs4.BeautifulSoup(driver.page_source, 'html5lib')
        article = soup.find('div', 'article-content')

        driver.close()
        return {
            'title': self.parse_title(soup),
            'paragraphs': [p.text for p in article.find_all('p')],
            'images': self.parse_images(soup),
            'metadata': self.parse_metadata(soup),
        }

    @functools.lru_cache(maxsize=128)
    def get_article(self, url):
        url = self.restore_url(url)

        r = self.session.get(url)
        if r.status_code == 404:
            # Some Javascript shit is happening here, use Selenium.
            return self.get_article_selenium(url)

        soup = bs4.BeautifulSoup(r.text, 'html5lib')

        return {
            'title': self.parse_title(soup),
            'paragraphs': self.parse_article_from_script(soup),
            'metadata': self.parse_metadata(soup),
            'images': self.parse_images(soup),
        }
