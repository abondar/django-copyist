django-copyist
==========================================

Tool for precise and efficient copying of Django models instances.

Do you live in fear of the day when PM will come to you
and ask to implement a copy feature for your root model,
that has a lot of relations and you know that it will be a pain to implement it in a way that will work properly?

Well, fear no more, as `django-copyist` got you covered


Features
--------

- **Precision** - Copy only what you need in a way that you need with help of custom copy actions.
- **Readability** - With declarative style config - you can easily see what and how is copied, no need to hop between models and parse it in your head.
- **Efficiency** - Unlike some other solutions and naive approaches, copyist is copying your data without recursive hopping between model instances, which gives it a magnitudes of speedup on big data sets.
- **Flexibility** - Copyist covers all steps that are there for data copy, including validation of data, pre-copy and post-copy actions. Copyist also work good with de-normalized data, not judging you for your choices.
- **Interactive** - Copyist provides a way to interact with the copy process, allowing application to see what exactly is going to be done, and propagate that info to end user to decide if he wants to go through with it.
- **Reusability** - With copyist your copy flow is not nailed down to model, allowing you defining different approaches for same model, and at the same time reuse existing configurations.

Motivation
----------

This project was build as in-house tool for project with complex hierarchy of models,
where we needed to copy them in a very particular way.

Existing solutions like `django-clone <https://github.com/tj-django/django-clone>`_  were designed
in a way that didn't fit our needs, as they required to modify models and
didn't allow to have full control over the copying process.

This project aims to provide a more flexible and efficient way to copy Django models instances, while
not affecting existing codebase.

Quickstart
==========

This pages aims to get you going with django-copyist as quickly as possible.

Installation
------------

To install with pip:

.. code-block:: console

   pip install django-copyist

To install with poetry:

.. code-block:: console

   poetry add django-copyist


Usage
-----------

`See quickstart in docs <https://abondar.github.io/django-copyist/quickstart.html>`_
