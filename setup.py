import setuptools

setuptools.setup(
    name='discord_bot',
    description='Discord Bot',
    author='Tyler D. North',
    author_email='ty_north@yahoo.com',
    install_requires=[
        'cryptography >= 2.9.2',
        'discord >= 1.0.1',
        'PyMySQL >= 1.0.2',
        'PyNaCl >= 1.4.0',
        'python-twitter >= 3.5',
        'SQLAlchemy >= 1.4.18',
        'youtube-dl >= 2021.2.22',
    ],
    entry_points={
        'console_scripts' : [
            'discord-bot = discord_bot.run_bot:main',
        ]
    },
    packages=setuptools.find_packages(exclude=['tests']),
<<<<<<< HEAD
    version='1.7.10',
=======
<<<<<<< HEAD
    version='1.7.9',
=======
    version='1.7.8',
>>>>>>> 15067b2... Move youtube logic into cogs completely
>>>>>>> dd76ea4... Move youtube logic into cogs completely
)
