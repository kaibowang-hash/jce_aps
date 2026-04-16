from setuptools import setup, find_packages

setup(
    name="jce_aps",
    version="0.0.1",
    description="Injection molding APS app for ERPNext/Frappe",
    author="OpenAI",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
