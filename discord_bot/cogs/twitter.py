import asyncio
import re
import typing

from discord.ext import commands
from requests.exceptions import ConnectionError as requests_connection_error
from twitter import Api
from twitter.error import TwitterError

from discord_bot.cogs.common import CogHelper
from discord_bot.database import TwitterSubscription, TwitterSubscriptionFilter

class Twitter(CogHelper):
    '''
    Subscribe to twitter accounts and post messages in channel
    '''
    def __init__(self, bot, db_session, logger, twitter_settings):
        super().__init__(bot, db_session, logger)
        self.twitter_settings = twitter_settings
        self.twitter_api = None
        self._restart_client()
        self.bot.loop.create_task(self.wait_loop())

    def _restart_client(self):
        self.logger.debug('Reloading twitter client')
        self.twitter_api = Api(
               consumer_key=self.twitter_settings['consumer_key'],
               consumer_secret=self.twitter_settings['consumer_secret'],
               access_token_key=self.twitter_settings['access_token_key'],
               access_token_secret=self.twitter_settings['access_token_secret'])

    async def _check_subscription(self, subscription, subscription_filters):
        self.logger.debug(f'Checking users twitter feed for '
                          f'new posts for user "{subscription.twitter_user_id}" since last post "{subscription.last_post}"')
        channel = self.bot.get_channel(int(subscription.channel_id))
        try:
            timeline = self.twitter_api.GetUserTimeline(user_id=subscription.twitter_user_id,
                                                        since_id=subscription.last_post,
                                                        include_rts=subscription.show_all_posts,
                                                        exclude_replies=not subscription.show_all_posts)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return

        try:
            timeline[-1].id
        except IndexError:
            self.logger.warning(f'Timeline empty for user {subscription.twitter_user_id}')
            return

        # Iterate through the list backwards so that the oldest tweets are first
        for post in timeline[::-1]:
            self.logger.debug(f'Checking post {post.id} from subscription "{subscription.id}"')
            if post.id == subscription.last_post:
                self.logger.debug(f'Reached last known post "{subscription.last_post}"')
                break

            # Check if post doesn't match any filters
            exclude_message = False
            for sub_filter in subscription_filters:
                if not re.match(sub_filter.regex_filter, post.text):
                    self.logger.info(f'Exlcuding post {post.id} because text "{post.text}" does not match regex filter "{sub_filter.regex_filter}"')
                    exclude_message = True
                    break

            if not exclude_message:
                message = f'https://twitter.com/{post.user.screen_name}/status/{post.id}'
                self.logger.info(f'Posting twitter message "{message}" to channel {channel.id}')
                await channel.send(message)

        # Oldest post will be first returned
        subscription.last_post = timeline[0].id
        self.db_session.commit()

    async def wait_loop(self):
        '''
        Our main player loop.
        '''
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.logger.debug("Checking twitter feeds")
            subscriptions = self.db_session.query(TwitterSubscription).all()
            for subscription in subscriptions:
                subscription_filters = self.db_session.query(TwitterSubscriptionFilter).\
                                            filter(TwitterSubscriptionFilter.twitter_subscription_id == subscription.id)
                await self._check_subscription(subscription, subscription_filters)
            await asyncio.sleep(300)

    @commands.group(name='twitter', invoke_without_command=False)
    async def twitter(self, ctx): #pylint:disable=no-self-use
        '''
        Planner functions
        '''
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid sub command passed...')

    @twitter.command(name='subscribe')
    async def subscribe(self, ctx, twitter_account, show_all_posts: typing.Optional[str] = ''):
        '''
        Subscribe to twitter account, and post updates in channel

        twitter_account :   Twitter account name to subscribe to
        show_all_posts  :   To show all posts, including retweets and replies use "show-all"
        '''
        # Strip twitter.com lead from string
        twitter_account = twitter_account.replace('https://twitter.com/', '')
        twitter_account = twitter_account.rstrip('/')
        self.logger.debug(f'Attempting to subscribe to username: {twitter_account}')
        try:
            user = self.twitter_api.GetUser(screen_name=twitter_account)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')
        # Then check if subscription exists
        subscription = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.twitter_user_id == user.id).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id)).first()
        if subscription:
            return await ctx.send(f'Already subscribed to user {twitter_account}')

        show_posts = show_all_posts.strip().lower() == 'show-all'
        try:
            timeline = self.twitter_api.GetUserTimeline(user_id=user.id, count=1,
                                                        include_rts=show_posts, exclude_replies=not show_posts)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')

        if len(timeline) == 0:
            return await ctx.send(f'No timeline found for user: {twitter_account}')

        last_post = timeline[0].id

        # Create new subscription
        args = {
            'twitter_user_id': user.id,
            'last_post': last_post,
            'channel_id': str(ctx.channel.id),
            'show_all_posts': show_posts,
        }
        self.logger.debug(f'Adding new subscription {args}')
        tw = TwitterSubscription(**args)
        self.db_session.add(tw)
        self.db_session.commit()
        return await ctx.send(f'Subscribed channel to twitter user {twitter_account}')

    @twitter.command(name='unsubscribe')
    async def unsubscribe(self, ctx, twitter_account):
        '''
        Unsubscribe channel from twitter account
        '''
        twitter_account = twitter_account.replace('https://twitter.com/', '')
        twitter_account = twitter_account.rstrip('/')
        self.logger.debug(f'Attempting to unsubscribe from username: {twitter_account} '
                          f'and channel id {ctx.channel.id}')
        try:
            user = self.twitter_api.GetUser(screen_name=twitter_account)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')
        # Then check if subscription exists
        subscription = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.twitter_user_id == user.id).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id)).first()
        if subscription:
            # Remove any filters from subscription
            self.db_session.query(TwitterSubscriptionFilter).\
                filter(TwitterSubscriptionFilter.twitter_subscription_id == subscription.id).delete()
            self.db_session.delete(subscription)
            self.db_session.commit()
            return await ctx.send(f'Unsubscribed to user {twitter_account}')
        return await ctx.send(f'No subscription found for user {twitter_account} in channel')

    @twitter.command(name='list-subscriptions')
    async def subscribe_list(self, ctx):
        '''
        List channel subscriptions
        '''
        subscriptions = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id))
        screen_names = []
        for subs in subscriptions:
            try:
                user = self.twitter_api.GetUser(user_id=subs.twitter_user_id)
                screen_names.append(user.screen_name)
            except (TwitterError, requests_connection_error) as error:
                self.logger.exception(f'Exception getting user: {error}')
                self._restart_client()
                return await ctx.send('Error getting twitter names')
        message = '\n'.join(name for name in screen_names)
        return await ctx.send(f'```Subscribed to \n{message}```')


    @twitter.command(name='add-filter')
    async def add_filter(self, ctx, twitter_account, regex_filter):
        '''
        Add filter to account subscription

        twitter_account :   Twitter account name to add filter to, must already be subscribed
        regex_filter    :   Python regex filter, only posts that match filter will be shown
        '''
        # Strip twitter.com lead from string
        twitter_account = twitter_account.replace('https://twitter.com/', '')
        self.logger.debug(f'Attempting to add filter "{regex_filter}" to subscription "{twitter_account}"')
        try:
            user = self.twitter_api.GetUser(screen_name=twitter_account)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')
        # Then check if subscription exists
        subscription = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.twitter_user_id == user.id).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id)).first()
        if not subscription:
            self.logger.error(f'Unable to find subscription for twitter account "{twitter_account}"')
            return await ctx.send(f'Unable to find subscription for twitter account "{twitter_account}"')

        # Attempt to compile filter
        try:
            re.compile(regex_filter)
        except re.error:
            self.logger.error(f'Invalid regex filter given "{regex_filter}"')
            return await ctx.send(f'Invalid regex filter given "{regex_filter}"')


        subscription_filter = TwitterSubscriptionFilter(
            twitter_subscription_id = subscription.id,
            regex_filter=regex_filter,
        )
        self.db_session.add(subscription_filter)
        self.db_session.commit()

        return await ctx.send(f'Filter "{regex_filter}" added to subscription "{twitter_account}"')

    @twitter.command(name='remove-filter')
    async def remove_filter(self, ctx, twitter_account, regex_filter):
        '''
        Remove filter from account subscription

        twitter_account :   Twitter account name to remove filter from, must already be subscribed
        regex_filter    :   Python regex filter
        '''
        # Strip twitter.com lead from string
        twitter_account = twitter_account.replace('https://twitter.com/', '')
        self.logger.debug(f'Attempting to remote filter "{regex_filter}" to subscription "{twitter_account}"')
        try:
            user = self.twitter_api.GetUser(screen_name=twitter_account)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')
        # Then check if subscription exists
        subscription = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.twitter_user_id == user.id).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id)).first()
        if not subscription:
            self.logger.error(f'Unable to find subscription for twitter account "{twitter_account}"')
            return await ctx.send(f'Unable to find subscription for twitter account "{twitter_account}"')

        self.db_session.query(TwitterSubscriptionFilter).\
            filter(TwitterSubscriptionFilter.twitter_subscription_id == subscription.id).\
            filter(TwitterSubscriptionFilter.regex_filter == regex_filter).delete()
        return await ctx.send(f'Removed all filters matching "{regex_filter}" from subscription "{twitter_account}"')

    @twitter.command(name='list-filters')
    async def list_filters(self, ctx, twitter_account):
        '''
        List filter on account subscription

        twitter_account :   Twitter account name to list filters for, must already be subscribed
        '''
        # Strip twitter.com lead from string
        twitter_account = twitter_account.replace('https://twitter.com/', '')
        try:
            user = self.twitter_api.GetUser(screen_name=twitter_account)
        except (TwitterError, requests_connection_error) as error:
            self.logger.exception(f'Exception getting user: {error}')
            self._restart_client()
            return await ctx.send(f'Error from twitter api "{error}"')
        # Then check if subscription exists
        subscription = self.db_session.query(TwitterSubscription).\
                            filter(TwitterSubscription.twitter_user_id == user.id).\
                            filter(TwitterSubscription.channel_id == str(ctx.channel.id)).first()
        if not subscription:
            self.logger.error(f'Unable to find subscription for twitter account "{twitter_account}"')
            return await ctx.send(f'Unable to find subscription for twitter account "{twitter_account}"')


        filters = self.db_session.query(TwitterSubscriptionFilter).\
                    filter(TwitterSubscriptionFilter.twitter_subscription_id == subscription.id)

        filter_message = '\n'.join(f.regex_filter for f in filters)
        return await ctx.send(f'```Filters\n{filter_message}```')
