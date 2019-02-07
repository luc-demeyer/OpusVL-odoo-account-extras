# -*- coding: utf-8 -*-

import requests
import json
import logging
import werkzeug
import urllib

from odoo import models, fields, api, exceptions
from datetime import datetime, timedelta
from urllib.parse import urlparse

_logger = logging.getLogger(__name__)


class MtdHelloWorld(models.Model):
    _name = 'mtd.hello_world'
    _description = "Hello world to test connection between Odoo and HMRC"
    
    name = fields.Char(required=True, readonly=True)
    api_id = fields.Many2one(comodel_name="mtd.api", string="Api Name", required=True)
    hmrc_configuration = fields.Many2one(comodel_name="mtd.hmrc_configuration", string="HMRC Configuration")
    scope = fields.Char(related="api_id.scope")
    response_from_hmrc = fields.Text(string="Response From HMRC", readonly=True)
    endpoint_name = fields.Char(string="which_button")
    path = fields.Char(string="sandbox_url")

    @api.multi
    def action_hello_world_connection(self):
        if not self.hmrc_configuration:
            raise exceptions.Warning("Please select HMRC configuration before continuing!")
        # making sure that the endpoint is what we have used in the data file as the name can be changed anytime.
        endpoint_record = self.env['ir.model.data'].search([
            ('res_id', '=', self.id), ('model', '=', 'mtd.hello_world')
        ])

        request_handler = {
            "mtd_hello_world_endpoint": "_handle_mtd_hello_world_endpoint",
            "mtd_hello_application_endpoint": "_handle_mtd_hello_application_endpoint",
            "mtd_hello_user_endpoint": "_handle_mtd_hello_user_endpoint",
        }
        handler_name = request_handler.get(endpoint_record.name)
        if handler_name:
            handle_request = getattr(self, handler_name)()
            return handle_request
        else:
            raise exceptions.Warning("Could not connect to HMRC! \nThis is not a valid HMRC service connection")

    def _handle_mtd_hello_world_endpoint(self):
        self.endpoint_name = "helloworld"
        self.path = "/hello/world"
        version = self._json_command('version')
        _logger.info(self.connection_button_clicked_log_message())
        return version

    def _handle_mtd_hello_application_endpoint(self):
        self.endpoint_name = "application"
        self.path = "/hello/application"
        version = self._json_command('version')
        _logger.info(self.connection_button_clicked_log_message())
        return version

    def _handle_mtd_hello_user_endpoint(self):
        self.endpoint_name = "user"
        self.path = "/hello/user"
        _logger.info(self.connection_button_clicked_log_message())
        # search for token record for the API
        import pdb; pdb.set_trace()
        token_record = self.env['mtd.api_tokens'].search([('api_id', '=', self.api_id.id)])
        _logger.info(
            "Connection button Clicked - endpoint name {name}, and the api is :- {api_id} ".format(
                name=self.name,
                api_id=self.api_id
            )
        )
        if token_record.access_token and token_record.refresh_token:
            _logger.info(
                "Connection button Clicked - endpoint name {name}, ".format(name=self.name) +
                "We have access token and refresh token"
            )
            version = self._json_command('version')
            return version
        else:
            _logger.info(
                "Connection button Clicked - endpoint name {name}, No access token ".format(name=self.name) +
                "found and no refresh_token found from the token record table."
            )
            authorisation_tracker = self.env['mtd.api_request_tracker'].search([('closed', '=', False)])
            _logger.info(
                "Connection button Clicked - endpoint name {name}, ".format(name=self.name) +
                "Checking to see if a request is in process"
            )
            create_date = fields.Datetime.from_string(authorisation_tracker.create_date)
            time_10_mins_ago = (datetime.utcnow() - timedelta(minutes=10))
            if authorisation_tracker:
                authorised_code_expired = create_date <= time_10_mins_ago
                if authorised_code_expired:
                    # we can place a new request and close this request.
                    authorisation_tracker.closed = 'timed_out'
                    _logger.info(
                        "Connection button Clicked - endpoint name {name}, no Pending requests".format(name=self.name)
                    )
                    return self.get_user_authorisation()
                else:
                    # The request made was within 10 mins so the user has to wait.
                    raise exceptions.Warning(
                        "An authorisation request is already in process!!!\n " +
                        "Please try again later"
                    )
            else:
                return self.get_user_authorisation()

    def connection_button_clicked_log_message(self):
        return "Connection button Clicked - endpoint name {name}, redirect URL:- {redirect}, Path url:- {path}".format(
                name=self.name,
                redirect=self.hmrc_configuration.redirect_url,
                path=self.path
            )

    def _json_command(self, command, timeout=3, record_id=None):
        # this will determine where we have come from
        # if there is no record_id then we know we already had valid record to gain all the information for hello user
        _logger.info(
            "_json_command - has record_id been provided?:- {record_id}".format(record_id=record_id)
        )
        if record_id:
            self = self.env['mtd.hello_world'].search([('id', '=', record_id)])
            _logger.info(
                "_json_command - we need to find the record and assign it to self"
            )
        token_record = self.env['mtd.api_tokens'].search([('api_id', '=', self.api_id.id)])
        access_token = token_record.access_token if token_record else ""
        # may not newed next line of code will need to look into this further while testing.
        # refresh_token = token_record.refresh_token if token_record else ""
        
        header_items = {"Accept": "application/vnd.hmrc.1.0+json"}
        if self.endpoint_name == "application":
            header_items["authorization"] = ("Bearer "+self.hmrc_configuration.server_token)
        elif self.endpoint_name == "user":
            # need to first check if the user has any accessToken and refreshtoken
            # If not we need to proceed to the first and second step and then come to this step.
            header_items["authorization"] = ("Bearer "+str(access_token))

        hmrc_connection_url = "{}{}".format(self.hmrc_configuration.hmrc_url, self.path)
        _logger.info(
            "_json_command - hmrc connection url:- {connection_url}, ".format(connection_url=hmrc_connection_url) +
            "headers:- {header}".format(header=header_items)
        )
        response = requests.get(hmrc_connection_url, timeout=3, headers=header_items)
        response_token = json.loads(response.text)
        _logger.info(
            "_json_command - received respponse of the request:- {response}, ".format(response=response) +
            "and its text:- {response_token}".format(response_token=response_token)
        )
        if response.ok:
            success_message = (
                "Date {date}     Time {time} \n".format(date=datetime.utcnow().date(), time=datetime.utcnow().time())
                + "Congratulations ! The connection succeeded. \n"
                + "Please check the log below for details. \n\n"
                + "Connection Status Details: \n"
                + "Request Sent: \n{connection_url} \n\n".format(connection_url=hmrc_connection_url)
                + "Response Received: \n{message}".format(message=response_token['message'])
            )
            self.response_from_hmrc = success_message
            if record_id:
                _logger.info(
                    "_json_command - response received ok we have record id so we " +
                    "return werkzeug.utils.redirect "
                )
                action = self.env.ref('account_mtd.action_mtd_hello_world')
                menu_id = self.env.ref('account_mtd.submenu_mtd_hello_world')
                _logger.info(
                    "-------Redirect is:- " +
                    "/web#id={id}&view_type=form&model=mtd.hello_world&".format(id=record_id) +
                    "menu_id={menu}&action={action}".format(menu=menu_id.id, action=action.id)
                )
                return werkzeug.utils.redirect(
                    "/web#id={id}&view_type=form&model=mtd.hello_world&".format(id=record_id) +
                    "menu_id={menu}&action={action}".format(menu=menu_id.id, action=action.id)
                )
            return True
            
        elif (response.status_code == 401 and
              self.endpoint_name == "user" and
              response_token['message'] == "Invalid Authentication information provided"):
            _logger.info(
                "_json_command - code 401 found, user button clicked,  " +
                "and message was:- {} ".format(response_token['message'])
            )
            return self.refresh_user_authorisation(token_record)
            
        else:
            response_token = json.loads(response.text)
            error_message = self.consturct_error_message_to_display(
                url=hmrc_connection_url,
                code=response.status_code,
                message=response_token['error_description'],
                error=response_token['error']
            )
            _logger.info("_json_command - other error found:- {error} ".format(error=error_message))
            self.response_from_hmrc = error_message
            if record_id:
                action = self.env.ref('account_mtd.action_mtd_hello_world')
                menu_id = self.env.ref('account_mtd.submenu_mtd_hello_world')
                return werkzeug.utils.redirect(
                    '/web#id={id}&view_type=form&model=mtd.hello_world'.format(id=record_id) +
                    '&menu_id={menu}&action={action}'.format(menu=menu_id.id, action=action.id)
                )
            return True
    
    @api.multi
    def get_user_authorisation(self):

        tracker_api = self.create_tracker_record()
        redirect_uri = "{}/auth-redirect".format(self.hmrc_configuration.redirect_url)
        state = ""
        # State is optional
        if self.hmrc_configuration.state:
            state = "&state={}".format(self.hmrc_configuration.state)
        # scope needs to be percent encoded
        scope = urllib.parse.quote_plus(self.scope)
        authorisation_url_prefix = "https://test-api.service.hmrc.gov.uk/oauth/authorize?"
        _logger.info("(Step 1) Get authorisation - authorisation URI used:- {}".format(authorisation_url_prefix))
        authorisation_url = (
            "{url}response_type=code&client_id={client_id}&scope={scope}{state}&redirect_uri={redirect}".format(
                url=authorisation_url_prefix,
                client_id=self.hmrc_configuration.client_id,
                scope=scope,
                state=state,
                redirect=redirect_uri
            )
        )
        _logger.info(
            "(Step 1) Get authorisation - authorisation URI " +
            "used to send request:- {url}".format(url=authorisation_url)
        )
        response = requests.get(authorisation_url, timeout=3)
        # response_token = json.loads(req.text)
        _logger.info(
            "(Step 1) Get authorisation - received response of the request:- {response}".format(response=response)
        )
        return self.handle_user_authorisation_response(response, authorisation_url, tracker_api)

    def handle_user_authorisation_response(self, response=None, url=None, tracker=None):
        if response.ok:
            return {'url': url, 'type': 'ir.actions.act_url', 'target': 'self', 'res_id': self.id}
        else:
            response_token = json.loads(response.text)
            error_message = self.consturct_error_message_to_display(
                url=url,
                code=response.status_code,
                message=response_token['error_description'],
                error=response_token['error']
            )
            self.response_from_hmrc = error_message
            # close the request so a new request can be made.
            tracker.closed = 'response'

            return werkzeug.utils.redirect(
                '/web#id={id}&view_type=form&model=mtd.hello_world&menu_id={menu}&action={action}'.format(
                    id=self.id,
                    menu=tracker.menu_id,
                    action=tracker.action
                )
            )

    def create_tracker_record(self):
        # get the action id and menu id and store it in the tracker table
        # if we get an error on authorisation or while exchanging tokens we need to use these to redirect.
        action = self.env.ref('account_mtd.action_mtd_hello_world')
        menu_id = self.env.ref('account_mtd.submenu_mtd_hello_world')

        # Update the information in the api tracker table
        _logger.info("(Step 1) Get authorisation")
        tracker_api = self.env['mtd.api_request_tracker']
        tracker_api = tracker_api.create({
            'user_id': self._uid,
            'api_id': self.api_id.id,
            'api_name': self.api_id.name,
            'endpoint_id': self.id,
            'request_sent': True,
            'action': action.id,
            'menu_id': menu_id.id,
        })
        return tracker_api

    @api.multi        
    def exchange_user_authorisation(self, auth_code, record_id, tracker_id):
        _logger.info("(Step 2) exchange authorisation code")
        api_tracker = self.env['mtd.api_request_tracker'].search([('id', '=', tracker_id)])
        api_token = self.env['mtd.api_tokens'].search([('api_id', '=', api_tracker.api_id.id)])

        if api_token:
            api_token.authorisation_code = auth_code
        else:
            api_token.create({
                'api_id': api_tracker.api_id.id,
                'api_name': api_tracker.api_name,
                'authorisation_code': auth_code,
            })
        record = self.env['mtd.hello_world'].search([('id', '=', record_id)])
        token_location_uri = "https://test-api.service.hmrc.gov.uk/oauth/token"
        client_id = record.hmrc_configuration.client_id
        client_secret = record.hmrc_configuration.client_secret
        redirect_uri = "{}/auth-redirect".format(record.hmrc_configuration.redirect_url)

        # When exchanging the authorisation code for access token we need to sent a post request
        # passing in following parameters.
        data_user_info = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'code': auth_code
        }
        _logger.info(
            "(Step 2) exchange authorisation code - Data which will be " +
            "sent in the request:- {}".format(json.dumps(data_user_info))
        )
        headers = {'Content-Type': 'application/json'}
        _logger.info(
            "(Step 2) exchange authorisation code - headers which will be "
            "sent in the request:- {}".format(headers)
        )
        response = requests.post(token_location_uri, data=json.dumps(data_user_info), headers=headers)
        response_token = json.loads(response.text)
        _logger.info(
            "(Step 2) exchange authorisation code - " +
            "received response of the request:- {response}, ".format(response=response) +
            "and its text:- {res_token}".format(res_token=response_token)
        )
        # get the record which we created when sending the request and update the closed column
        # As this determines whether we can place another request or not
        record_tracker = self.env['mtd.api_request_tracker'].search([('closed', '=', False)])
        record_tracker.closed = 'response'
        if response.ok:
            if not api_token:
                api_token = self.env['mtd.api_tokens'].search([('authorisation_code', '=', auth_code)])
            _logger.info(
                "(Step 2) exchange authorisation code " +
                "- api_token table id where info is stored:- {}".format(api_token)
            )
            api_token.access_token = response_token['access_token']
            api_token.refresh_token = response_token['refresh_token']
            api_token.expires_in = json.dumps(response_token['expires_in'])
            api_token.access_token_recieved_date = datetime.utcnow()
            version = self._json_command('version', record_id=record_id)
            return version
        else:
            error_message = self.consturct_error_message_to_display(
                url=token_location_uri,
                code=response.status_code,
                message=response_token['error_description'],
                error=response_token['error']
            )
            record.response_from_hmrc = error_message
            _logger.info(
                "(Step 2) exchange authorisation code - log:- {}".format(error_message)
            )
            _logger.info(
                "(Step 2) exchange authorisation code - redirect URI :- " +
                "/web#id={id}&view_type=form&model=mtd.hello_world&menu_id={menu}&action={action}".format(
                    id=record_id,
                    menu=api_tracker.menu_id,
                    action=api_tracker.action
                )
            )
            return werkzeug.utils.redirect(
                "/web#id={id}&view_type=form&model=mtd.hello_world&menu_id={menu}&action={action}".format(
                    id=record_id,
                    menu=api_tracker.menu_id,
                    action=api_tracker.action
                )
            )

    def refresh_user_authorisation(self, token_record=None):
        _logger.info("(Step 4) refresh_user_authorisation - token_record:- {}".format(token_record))
        api_token = self.env['mtd.api_tokens'].search([('id', '=', token_record.id)])
        hmrc_authorisation_url = "{}/oauth/token".format(self.hmrc_configuration.hmrc_url)
        _logger.info(
            "(Step 4) refresh_user_authorisation - hmrc authorisation url:- {}".format(hmrc_authorisation_url)
        )

        data_user_info = {
            'client_secret': self.hmrc_configuration.client_secret,
            'client_id': self.hmrc_configuration.client_id,
            'grant_type': 'refresh_token',
            'refresh_token': api_token.refresh_token
        }
        headers = {
            'Content-Type': 'application/json',
        }
        _logger.info(
            "(Step 4) refresh_user_authorisation - data to send in request:- {}".format(data_user_info)
        )
        _logger.info(
            "(Step 4) refresh_user_authorisation - headers to send in request:- {}".format(headers)
        )
        response = requests.post(hmrc_authorisation_url, data=json.dumps(data_user_info), headers=headers)
        response_token = json.loads(response.text)
        _logger.info(
            "(Step 4) refresh_user_authorisation - received response of the " +
            "request:- {resp}, and its text:- {resp_token}".format(resp=response, resp_token=response_token)
        )
        if response.ok:
            api_token.access_token = response_token['access_token']
            api_token.refresh_token = response_token['refresh_token']
            api_token.expires_in = json.dumps(response_token['expires_in'])
            version = self._json_command('version')
            return version
        elif response.status_code == 400 and response_token['message'] == "Bad Request":
            _logger.info(
                "(Step 4) refresh_user_authorisation - error 400, obtaining new access code and refresh token"
            )
            return self.get_user_authorisation()
        else:
            error_message = self.consturct_error_message_to_display(
                url=hmrc_authorisation_url,
                code=response.status_code,
                message=response_token['message']
            )

            _logger.info(
                "(Step 4) refresh_user_authorisation - other error:- {}".format(error_message)
            )
            self.response_from_hmrc = error_message
            return True

    def consturct_error_message_to_display(self, url=None, code=None, message=None, error=None):
        if error:
            error = "\n{}".format(error)
        error_message = (
                "Date {date}     Time {time} \n".format(date=datetime.now().date(), time=datetime.now().time())
                + "Sorry. The connection failed ! \n"
                + "Please check the log below for details. \n\n"
                + "Connection Status Details: \n"
                + "Request Sent: \n{auth_url} \n\n".format(auth_url=url)
                + "Error Code:\n{code} \n\n".format(code=code)
                + "Response Received: {error}\n{message}".format(error=error, message=message)
        )

        return error_message
