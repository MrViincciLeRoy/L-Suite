from django.core.management.base import BaseCommand
from apps.main.models import TransactionCategory

SEED_CATEGORIES = [
    {
        'name': 'Groceries',
        'transaction_type': 'debit',
        'color': 4,
        'keywords': 'supermarket,checkers,woolworths,pick n pay,spar,shoprite,food lover,clicks food,spaza,tucksho,mart,makro,game store,usave,s2s,ccn',
        'tags': 'checkers,woolworths,spar,shoprite,pnp,foodlovers',
    },
    {
        'name': 'Fuel',
        'transaction_type': 'debit',
        'color': 1,
        'keywords': 'caltex,shell,sasol,engen,total,bp,astron,fuel,petrol',
        'tags': 'caltex,shell,sasol,engen,total,bp',
    },
    {
        'name': 'Transport',
        'transaction_type': 'debit',
        'color': 2,
        'keywords': 'uber,bolt,taxi,gautrain,metrobus,intercape,greyhound,ride,trip',
        'tags': 'uber,bolt',
    },
    {
        'name': 'Food & Dining',
        'transaction_type': 'debit',
        'color': 3,
        'keywords': "nando,kfc,mcdonalds,mcdonald,steers,wimpy,debonairs,fishaways,chicken licken,burger king,roman's,pizza,restaurant,cafe,bakery,coffee,mugg,bean,ocean basket",
        'tags': "nandos,kfc,mcdonalds,steers,wimpy,debonairs",
    },
    {
        'name': 'Entertainment',
        'transaction_type': 'debit',
        'color': 5,
        'keywords': 'netflix,showmax,dstv,spotify,apple music,youtube,amazon prime,hulu,disney,cinema,ster-kinekor,nu metro,gaming,playstation,xbox',
        'tags': 'netflix,showmax,dstv,spotify',
    },
    {
        'name': 'Healthcare',
        'transaction_type': 'debit',
        'color': 6,
        'keywords': 'dischem,pharmacy,clicks,clinic,hospital,doctor,dentist,optometrist,medirite,medihelp,discovery health,bonitas,momentum health',
        'tags': 'dischem,clicks',
    },
    {
        'name': 'Telecommunications',
        'transaction_type': 'debit',
        'color': 7,
        'keywords': 'vodacom,mtn,telkom,cell c,airtime,data,prepaid,recharge,rain,afrihost,webafrica',
        'tags': 'vodacom,mtn,telkom,cellc',
    },
    {
        'name': 'Banking & Finance',
        'transaction_type': 'debit',
        'color': 8,
        'keywords': 'fnb,absa,nedbank,standard bank,capitec,investec,african bank,service fee,bank charge,atm fee,monthly fee,admin fee,interest charged,insurance premium,monthly account admin,branch card replacement,print statement',
        'tags': 'fnb,absa,nedbank,capitec',
    },
    {
        'name': 'Bank Charges',
        'transaction_type': 'debit',
        'color': 13,
        'keywords': 'set-off,setoff,sms payment notification,sms notification,stop payment,unpaid debit,dishonour,penalty fee,returned item,early settlement,account maintenance,debit order fee,sms fee,card fee,statement fee,dispute fee',
        'tags': 'setoff,sms,stop payment',
    },
    {
        'name': 'Utilities',
        'transaction_type': 'debit',
        'color': 9,
        'keywords': 'eskom,city power,municipality,rates,water,electricity,prepaid electricity,sanitation,refuse,tshwane,joburg,ekurhuleni,cape town metro',
        'tags': 'eskom,tshwane,joburg',
    },
    {
        'name': 'Shopping',
        'transaction_type': 'debit',
        'color': 10,
        'keywords': 'takealot,amazon,mr price,ackermans,pep,jet,woolworths clothing,h&m,zara,edgars,truworths,foschini,sportsmans,outdoor,builders,leroy merlin',
        'tags': 'takealot,mrprice,ackermans,pep',
    },
    {
        'name': 'Income',
        'transaction_type': 'credit',
        'color': 11,
        'keywords': 'salary,payroll,wages,payment received,transfer received,received from,transfer in,deposit,commission,bonus,dividend,refund,payshap payment received,payshap received',
        'tags': 'salary,payroll,payshap',
    },
    {
        'name': 'Transfer',
        'transaction_type': 'debit',
        'color': 12,
        'keywords': 'transfer to,send money,ewallet,capitec pay,fnb pay,snapscan,zapper,payfast,peach payments,live better,round-up,round up,live better round-up',
        'tags': 'ewallet,snapscan,livebetter',
    },
]


class Command(BaseCommand):
    help = 'Seed default transaction categories with keywords and tags'

    def add_arguments(self, parser):
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite keywords/tags on existing categories',
        )

    def handle(self, *args, **options):
        overwrite = options['overwrite']
        created = 0
        updated = 0
        skipped = 0

        for data in SEED_CATEGORIES:
            cat, is_new = TransactionCategory.objects.get_or_create(
                name=data['name'],
                defaults={
                    'transaction_type': data['transaction_type'],
                    'keywords': data['keywords'],
                    'tags': data['tags'],
                    'color': data['color'],
                    'active': True,
                }
            )

            if is_new:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {cat.name}'))
            elif overwrite:
                cat.keywords = data['keywords']
                cat.tags = data['tags']
                cat.transaction_type = data['transaction_type']
                cat.save(update_fields=['keywords', 'tags', 'transaction_type'])
                updated += 1
                self.stdout.write(self.style.WARNING(f'  Updated: {cat.name}'))
            else:
                skipped += 1
                self.stdout.write(f'  Skipped (exists): {cat.name}')

        self.stdout.write(self.style.SUCCESS(
            f'\nDone — {created} created, {updated} updated, {skipped} skipped.'
        ))
        self.stdout.write('Run with --overwrite to force-update existing categories.')