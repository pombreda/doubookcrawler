# -*- coding: utf-8 -*-
import random
try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse

import scrapy
from scrapy import Request
from scrapy import log

from doubookcrawler.items import BookItem, CommentItem
from doubookcrawler.models import CrawledURL


class BookSpider(scrapy.Spider):
    name = "book"
    allowed_domains = ["book.douban.com"]
    start_urls = (
        'http://book.douban.com/tag/',
    )
    handle_httpstatus_list = [302, 403]

    def __init__(self, *args, **kwargs):
        super(BookSpider, self).__init__(*args, **kwargs)
        self.crawled_urls = CrawledURL.get_urls()

    def is_banned(self, response):
        banned_status = self.settings.get('RETRY_HTTP_CODES', [302, 403])
        return response.status in banned_status

    def start_requests(self):
        for url in self.start_urls:
            yield Request(
                url,
                callback=self.parse,
                meta={
                    'dont_redirect': True,
                    'handle_httpstatus_list': [302, 403]
                },
            )

    def parse(self, response):
        if self.is_banned(response):
            yield Request(
                response.url,
                callback=self.parse,
                meta={'dont_redirect': True, 'handle_httpstatus_list': [302]},
                dont_filter=True
            )
            return

        tags = response.xpath('//table[@class="tagCol"]/tbody/tr/td/a/@href')
        tags = tags.extract()
        random.shuffle(tags)
        for tag in tags:
            url = urlparse.urljoin(self.start_urls[0], tag)
            yield Request(url, callback=self.parse_tag)
            if self.settings['DEBUG']:
                break

    def parse_tag(self, response):
        if self.is_banned(response):
            yield Request(
                response.url,
                callback=self.parse_tag,
                meta={
                    'dont_redirect': True,
                    'handle_httpstatus_list': [302, 403]
                },
                dont_filter=True
            )
            return

        page_crawled = response.url in self.crawled_urls
        if not page_crawled:
            self.crawled_urls.append(response.url)
            CrawledURL.add_url(response.url)

        books = response.xpath('//ul/li[@class="subject-item"]/div[@class="info"]')
        for book in books:
            url = book.xpath('h2/a/@href').extract()
            if not page_crawled:
                title = book.xpath('h2/a/text()').extract()
                pub = book.xpath('div[@class="pub"]/text()').extract()
                rating = book.xpath('div/span[@class="rating_nums"]/text()').extract()
                if not (url and title and pub and rating):
                    self.log('Bad data for book, ignore', log.WARNING)
                    continue

                url_path = urlparse.urlsplit(url[0].strip()).path
                if url_path.endswith('/'):
                    url_path = url_path[:-1]
                book_id = url_path.split('/')[-1]
                book_pub = pub[0].strip().split('/')

                book_item = BookItem()
                book_item['id'] = int(book_id)
                book_item['title'] = title[0].strip()
                book_item['author'] = book_pub[0].strip()
                book_item['rating'] = float(rating[0])
                yield book_item

            comments_url = urlparse.urljoin(url[0], 'comments/')
            yield Request(comments_url, callback=self.parse_comments)

            if self.settings['DEBUG']:
                break

        pager = response.xpath('//div[@class="paginator"]')
        if not pager:
            self.log('No more pages, return', log.INFO)
            return
        next_page = pager.xpath('span[@class="next"]/a/@href').extract()[0]
        next_url = urlparse.urljoin('http://book.douban.com', next_page)
        if not self.settings['DEBUG']:
            yield Request(next_url, callback=self.parse_tag)

    def parse_comments(self, response):
        if self.is_banned(response):
            yield Request(
                response.url,
                callback=self.parse_comments,
                meta={
                    'dont_redirect': True,
                    'handle_httpstatus_list': [302, 403]
                },
                dont_filter=True
            )
            return

        page_crawled = response.url in self.crawled_urls
        if not page_crawled:
            self.crawled_urls.append(response.url)
            CrawledURL.add_url(response.url)

        rating_classes = {
            'allstar50': 5,
            'allstar40': 4,
            'allstar30': 3,
            'allstar20': 2,
            'allstar10': 1,
        }
        if not page_crawled:
            url_path = urlparse.urlsplit(response.url).path
            book_id = url_path.split('/')[2]
            comments = response.xpath('//ul/li[@class="comment-item"]/h3')
            for comment in comments:
                vote = comment.xpath('span[@class="comment-vote"]/span/text()').extract()
                info = comment.xpath('span[@class="comment-info"]')
                user = info.xpath('a/text()').extract()
                rating = info.xpath('span[1]/@class').extract()
                if not (vote and user and rating):
                    self.log('Bad data for comment, ignore', log.WARNING)
                    continue

                vote = int(vote[0])
                user = user[0].strip()
                rating = rating[0].replace('user-stars', '').replace('rating', '')
                rating = rating.strip()
                rating_num = rating_classes.get(rating, 0)
                if rating_num == 0:
                    self.log('Bad rating 0 for comment, ignore', log.INFO)
                    continue

                comment_item = CommentItem()
                comment_item['book_id'] = int(book_id)
                comment_item['user'] = user
                comment_item['rating'] = rating_num
                comment_item['vote'] = vote
                yield comment_item

                if self.settings['DEBUG']:
                    break

        pager = response.xpath('//ul[@class="comment-paginator"]/li[3]/a/@href')
        if not pager:
            return
        next_page = pager.extract()[0]
        next_url = urlparse.urljoin(response.url, next_page)
        if not self.settings['DEBUG']:
            yield Request(next_url, callback=self.parse_comments)
