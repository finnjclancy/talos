from enum import Enum
from typing import Any, Optional

import tweepy
from googleapiclient import discovery
from langchain.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from ..models.evaluation import EvaluationResult
from ..settings import PerspectiveSettings
from ..skills.twitter_persona import TwitterPersonaSkill
from .twitter_client import TweepyClient, TwitterClient
from .twitter_evaluator import DefaultTwitterAccountEvaluator, TwitterAccountEvaluator

MODERATION_THRESHOLD = 0.7


class TwitterToolName(str, Enum):
    POST_TWEET = "post_tweet"
    GET_ALL_REPLIES = "get_all_replies"
    REPLY_TO_TWEET = "reply_to_tweet"
    GET_FOLLOWER_COUNT = "get_follower_count"
    GET_FOLLOWING_COUNT = "get_following_count"
    GET_TWEET_ENGAGEMENT = "get_tweet_engagement"
    EVALUATE_ACCOUNT = "evaluate_account"
    EVALUATE_CRYPTO_INFLUENCER = "evaluate_crypto_influencer"
    GENERATE_PERSONA_PROMPT = "generate_persona_prompt"


class TwitterToolArgs(BaseModel):
    tool_name: TwitterToolName = Field(..., description="The name of the tool to run")
    tweet: str | None = Field(None, description="The content of the tweet")
    tweet_id: str | None = Field(None, description="The ID of the tweet")
    username: str | None = Field(None, description="The username of the user")
    search_query: str | None = Field(None, description="The search query to use")


class TwitterTool(BaseTool):
    name: str = "twitter_tool"
    description: str = "Provides tools for interacting with the Twitter API."
    args_schema: type[BaseModel] = TwitterToolArgs
    twitter_client: Optional[TwitterClient] = None
    account_evaluator: Optional[TwitterAccountEvaluator] = None
    perspective_client: Optional[Any] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        twitter_client: Optional[TwitterClient] = None,
        account_evaluator: Optional[TwitterAccountEvaluator] = None,
    ):
        super().__init__()
        self.twitter_client = twitter_client or TweepyClient()
        self.account_evaluator = account_evaluator or DefaultTwitterAccountEvaluator()
        self.perspective_client = self._initialize_perspective_client()

    def _initialize_perspective_client(self) -> Optional[Any]:
        """Initializes the Perspective API client."""
        try:
            settings = PerspectiveSettings()
            if not settings.PERSPECTIVE_API_KEY:
                return None
            return discovery.build(
                "commentanalyzer",
                "v1alpha1",
                developerKey=settings.PERSPECTIVE_API_KEY,
                discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
                static_discovery=False,
            )
        except ValueError:
            return None

    def post_tweet(self, tweet: str) -> str:
        """Posts a tweet."""
        if self.perspective_client:
            if not self.is_content_appropriate(tweet):
                return "Tweet not sent. Content is inappropriate."
        assert self.twitter_client is not None
        self.twitter_client.post_tweet(tweet)
        return "Tweet posted successfully."

    def get_all_replies(self, tweet_id: str) -> list[tweepy.Tweet]:
        """Gets all replies to a tweet."""
        # This functionality is not yet migrated to the new TwitterClient
        raise NotImplementedError

    def reply_to_tweet(self, tweet_id: str, tweet: str) -> str:
        """Replies to a tweet."""
        if self.perspective_client:
            if not self.is_content_appropriate(tweet):
                return "Tweet not sent. Content is inappropriate."
        assert self.twitter_client is not None
        self.twitter_client.reply_to_tweet(tweet_id, tweet)
        return "Tweet posted successfully."

    def is_content_appropriate(self, text: str) -> bool:
        """
        Checks if the content is appropriate using the Perspective API.

        Args:
            text: The text to analyze.

        Returns:
            True if the content is appropriate, False otherwise.
        """
        if not self.perspective_client:
            return True

        analyze_request = {
            "comment": {"text": text},
            "requestedAttributes": {"TOXICITY": {}},
        }

        response = self.perspective_client.comments().analyze(body=analyze_request).execute()
        toxicity_score = response["attributeScores"]["TOXICITY"]["summaryScore"]["value"]

        return toxicity_score < MODERATION_THRESHOLD

    def get_follower_count(self, username: str) -> int:
        """Gets the follower count for a user."""
        assert self.twitter_client is not None
        user = self.twitter_client.get_user(username)
        return user.public_metrics.followers_count

    def get_following_count(self, username: str) -> int:
        """Gets the following count for a user."""
        assert self.twitter_client is not None
        user = self.twitter_client.get_user(username)
        return user.public_metrics.following_count

    def get_tweet_engagement(self, tweet_id: str) -> dict:
        """Gets the engagement for a tweet."""
        # This functionality is not yet migrated to the new TwitterClient
        raise NotImplementedError

    def evaluate_account(self, username: str) -> EvaluationResult:
        """Evaluates a Twitter account and returns a score."""
        assert self.twitter_client is not None
        assert self.account_evaluator is not None
        user = self.twitter_client.get_user(username)
        return self.account_evaluator.evaluate(user)

    def evaluate_crypto_influencer(self, username: str) -> dict:
        """Evaluates a Twitter account as a crypto influencer."""
        from .crypto_influencer_evaluator import CryptoInfluencerEvaluator

        assert self.twitter_client is not None
        evaluator = CryptoInfluencerEvaluator(self.twitter_client)
        user = self.twitter_client.get_user(username)
        result = evaluator.evaluate(user)

        return {"username": username, "score": result.score, "evaluation_data": result.additional_data}

    def generate_persona_prompt(self, username: str) -> str:
        """Generates a prompt to describe the voice and style of a specific twitter user."""
        assert self.twitter_client is not None
        persona_skill = TwitterPersonaSkill(twitter_client=self.twitter_client)
        response = persona_skill.run(username=username)
        return response.report

    def _run(self, tool_name: str, **kwargs):
        if tool_name == "post_tweet":
            return self.post_tweet(**kwargs)
        elif tool_name == "get_all_replies":
            return self.get_all_replies(**kwargs)
        elif tool_name == "reply_to_tweet":
            return self.reply_to_tweet(**kwargs)
        elif tool_name == "get_follower_count":
            return self.get_follower_count(**kwargs)
        elif tool_name == "get_following_count":
            return self.get_following_count(**kwargs)
        elif tool_name == "get_tweet_engagement":
            return self.get_tweet_engagement(**kwargs)
        elif tool_name == "evaluate_account":
            return self.evaluate_account(**kwargs)
        elif tool_name == "evaluate_crypto_influencer":
            return self.evaluate_crypto_influencer(**kwargs)
        elif tool_name == "generate_persona_prompt":
            return self.generate_persona_prompt(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
