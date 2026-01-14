from setuptools import setup, find_packages

setup(
    name="falcon-screener",
    version="0.1.0",
    description="Falcon Trading Platform - Multi-Profile Stock Screener",
    author="TradingAsBuddies",
    url="https://github.com/TradingAsBuddies/falcon-screener",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "falcon-core @ git+https://github.com/TradingAsBuddies/falcon-core.git",
        "requests>=2.32.3",
        "beautifulsoup4>=4.12.2",
        "lxml>=4.9.3",
        "schedule>=1.2.0",
        "pytz>=2023.3",
        "PyYAML>=6.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "falcon-screener=falcon_screener.multi_screener:main",
            "falcon-daily-report=falcon_screener.daily_report:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
