#!/usr/bin/env python

import os
import sys
import  logging

ROOT_PATH = os.path.abspath( os.path.join(os.path.dirname(__file__), "../../"))
sys.path.insert( 0, os.path.join(ROOT_PATH, 'libs'))
sys.path.insert( 0, os.path.join(ROOT_PATH, 'apps'))

from datetime import timedelta

import tornado.ioloop
import tornado.web
import tornado.httpserver
import tornado.template
from tornado.options import define, options

define("port", default=8443, help="port" )
define("db_echo", default=False, help="Prints every database command on the stdout" )
define("db_engine", default="sqlite:///" + os.path.join(ROOT_PATH, "db/", "bitex.sqlite"), help="SQLAlchemy database engine string")
define("ws_url", default="wss://www.bitex.com.br:8449/trade", help="Websocket trade host")
define("certfile",default=os.path.join(ROOT_PATH, "ssl/", "order_matcher_certificate.pem") , help="Certificate file" )
define("keyfile", default=os.path.join(ROOT_PATH, "ssl/", "order_matcher_privatekey.pem") , help="Private key file" )
define("order_matcher_log", default=os.path.join(ROOT_PATH, "logs/", "order_matcher_replay.log"), help="logging" )


tornado.options.parse_config_file(os.path.join(ROOT_PATH, "config/", "order_match.conf"))
tornado.options.parse_command_line()


from sqlalchemy.orm import scoped_session, sessionmaker

from order_matcher import config
from order_matcher.models import   engine, Order, User
from order_matcher.execution import  OrderMatcher
from order_matcher.views import OrderMatcherHandler

class AdminHandler(tornado.web.RequestHandler):
  def get(self, *args, **kwargs):
    loader = tornado.template.Loader(os.path.join(ROOT_PATH, 'static'))
    self.write( loader.load("admin.html").generate( ws_url=options.ws_url  ) )

class BitExHandler(tornado.web.RequestHandler):
  def get(self, *args, **kwargs):
    loader = tornado.template.Loader(os.path.join(ROOT_PATH, 'static'))
    self.write( loader.load("bitex.html").generate(ws_url=options.ws_url) )


class OrderMatcherApplication(tornado.web.Application):
  def __init__(self):
    handlers = [
      (r'/trade', OrderMatcherHandler),
      (r'/admin/.*', AdminHandler),

      (r"/images/(.*)",  tornado.web.StaticFileHandler, {"path": os.path.join(ROOT_PATH, 'static/images') }),
      (r"/css/(.*)",  tornado.web.StaticFileHandler, {"path": os.path.join(ROOT_PATH, 'static/css') }),
      (r"/js/(.*)",  tornado.web.StaticFileHandler, {"path": os.path.join(ROOT_PATH, 'static/js') }),

      (r'/.*', BitExHandler)
    ]
    settings = dict(
      cookie_secret=config.cookie_secret
    )
    tornado.web.Application.__init__(self, handlers, **settings)

    # Have one global connection.
    self.session = scoped_session(sessionmaker(bind=engine))

    # check BTC deposits every 5 seconds
    tornado.ioloop.IOLoop.instance().add_timeout(timedelta(seconds=5), self.cron_check_btc_deposits)

    self.replay_log = logging.getLogger("REPLAY")

    # log all users on the replay log
    users = self.session.query(User)
    for user in users:
      self.replay_log.info('DB_ENTITY,' + str(user))

    # Load all open orders
    orders = self.session.query(Order).filter(Order.status.in_(("0", "1"))).order_by(Order.created)
    for order in orders:
      self.replay_log.info('DB_ENTITY,' + str(order))
      OrderMatcher.get( order.symbol  ).match(self.session, order)



  def cron_check_btc_deposits(self):
    # TODO: Invoke bitcoind rpc process to check for all deposits

    # run it again 5 seconds later...
    tornado.ioloop.IOLoop.instance().add_timeout(timedelta(seconds=5), self.cron_check_btc_deposits)



def main():
  print 'port', options.port
  print 'ws_url', options.ws_url
  print 'db_echo', options.db_echo
  print 'db_engine', options.db_engine
  print 'certfile', options.certfile
  print 'keyfile', options.keyfile
  print 'order_matcher_log', options.order_matcher_log

  input_log_file_handler = logging.handlers.TimedRotatingFileHandler( options.order_matcher_log, when='MIDNIGHT')
  formatter = logging.Formatter('%(asctime)s - %(message)s')
  input_log_file_handler.setFormatter(formatter)

  replay_logger = logging.getLogger("REPLAY")
  replay_logger.setLevel(logging.INFO)
  replay_logger.addHandler(input_log_file_handler)

  replay_logger.info('START')
  replay_logger.info('PARAM,BEGIN')
  replay_logger.info('PARAM,port,' + str(options.port))
  replay_logger.info('PARAM,ws_url,' + str(options.ws_url))
  replay_logger.info('PARAM,db_echo,' + str(options.db_echo))
  replay_logger.info('PARAM,db_engine,' + str(options.db_engine))
  replay_logger.info('PARAM,certfile,' + str(options.certfile))
  replay_logger.info('PARAM,keyfile,' + str(options.keyfile))
  replay_logger.info('PARAM,order_matcher_log,' + str(options.order_matcher_log))
  replay_logger.info('PARAM,END')


  application = OrderMatcherApplication()

  ssl_options={
    "certfile": options.certfile,
    "keyfile": options.keyfile,
  }
  http_server = tornado.httpserver.HTTPServer(application,ssl_options=ssl_options)
  http_server.listen(options.port)

  tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
  main()
