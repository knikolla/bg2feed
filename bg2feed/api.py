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

from flask import Flask, render_template, Response
from feedgen.feed import FeedGenerator

from bg2feed import parser

app = Flask(__name__)

web = parser.GlobeParser()


def create_feed(title, stories):
    feed = FeedGenerator()
    feed.id('https://bostonglobe.com/today')
    feed.title(title)
    feed.link(href='https://bostonglobe.com')
    feed.description('Today\'s Boston Globe')

    for story in reversed(stories):
        item = feed.add_item()
        item.id(story['url'])
        item.title(story['title'])
        item.link(href=story['url'])
        downloaded = web.get_article(story['url'])
        if downloaded['metadata']:
            item.author(author={
                'name': downloaded['metadata'].get('author', 'BostonGlobe.com')})
            item.summary(summary=downloaded['metadata'].get('description'))
    return feed


@app.route('/feeds/top-stories')
def feed_top_stories():
    top_stories = web.find_top_stories()
    feed = create_feed('Boston Globe - Top Stories', top_stories)
    return Response(feed.atom_str())


@app.route('/feeds/section/<section>')
def feed_section(section):
    if section in ['world', 'nation']:
        # There is more stuff on this page
        stories = web.get_section(section)
    else:
        # Otherwise let's just parse it from the today page
        stories = web.find_section(section)

    feed = create_feed('Boston Globe - %s' % section.capitalize(), stories)
    return Response(feed.atom_str())


@app.route('/proxy/<path:url>')
def proxy(url):
    article = web.get_article(url)
    return render_template('template.html', **article)


if __name__ == '__main__':
    app.run(port=8080)
