"""LOOKING.CENTER uses the same HTTP country/card/actions as LOOKING.HOUSE."""
from Plugins.lookingHouse import lookingHouse


class lookingCenter(lookingHouse):
    url = 'https://looking.center'
