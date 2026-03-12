import csv
import os
import glob
from decimal import Decimal, InvalidOperation
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import IntegrityError
from stocks.models import Symbol, DailyPrice

"""
# Import a single year
python manage.py import_prices --dir ./data --year 2023 --granularity 1D

# Import a range of years
python manage.py import_prices --dir ./data --year 2001-2010 --granularity 1D

# Import with parallel processing for faster imports
python manage.py import_prices --dir ./data --year 2001-2023 --granularity 1D --parallel --workers 8

# Skip records that already exist in the database (for resuming interrupted imports)
python manage.py import_prices --dir ./data --year 2001-2023 --granularity 1D --skip-existing

# Perform a dry run to see what would be imported without actually saving
python manage.py import_prices --dir ./data --year 2023 --granularity 1D --dry-run
"""

class Command(BaseCommand):
    help = 'Import price data from CSV files with improved error handling'

    def add_arguments(self, parser):
        parser.add_argument('--dir', type=str, required=True, help='Directory containing CSV files')
        parser.add_argument('--year', type=str, required=True,
                          help='Year or year range to import (e.g., "2023" or "2001-2010")')
        parser.add_argument('--granularity', type=str, default='1D',
                          help='Granularity (default: 1D)')
        parser.add_argument('--parallel', action='store_true',
                          help='Import files in parallel')
        parser.add_argument('--workers', type=int, default=4,
                          help='Number of parallel workers')
        parser.add_argument('--skip-existing', action='store_true',
                          help='Skip records that already exist in database')
        parser.add_argument('--dry-run', action='store_true',
                          help='Perform a dry run without saving to database')

    def handle(self, *args, **options):
        data_dir = options['dir']
        year_spec = options['year']
        granularity = options['granularity']
        parallel = options['parallel']
        workers = options['workers']
        skip_existing = options['skip_existing']
        dry_run = options['dry_run']

        # Parse year range
        years = self._parse_year_range(year_spec)
        self.stdout.write(f"Years to import: {years}")

        total_imported = 0
        total_symbols = 0
        total_errors = 0
        years_processed = []

        # Process each year
        for year in years:
            self.stdout.write(self.style.NOTICE(f"\n{'='*60}"))
            self.stdout.write(self.style.NOTICE(f"Processing year {year}"))
            self.stdout.write(self.style.NOTICE(f"{'='*60}"))

            # Construct path based on directory structure
            import_path = os.path.join(data_dir, granularity, str(year))

            if not os.path.exists(import_path):
                self.stderr.write(f"Directory not found for year {year}: {import_path}")
                continue

            csv_files = [f for f in os.listdir(import_path) if f.endswith('.csv')]
            self.stdout.write(f"Found {len(csv_files)} files to import for year {year}")

            if not csv_files:
                self.stdout.write(f"No CSV files found for year {year}")
                continue

            # Import files for this year
            if parallel and len(csv_files) > 1:
                imported, symbols, errors = self._import_parallel(
                    csv_files, import_path, year, workers, skip_existing, dry_run
                )
            else:
                imported, symbols, errors = self._import_sequential(
                    csv_files, import_path, year, skip_existing, dry_run
                )

            total_imported += imported
            total_symbols += symbols
            total_errors += errors
            years_processed.append(year)

            self.stdout.write(self.style.SUCCESS(
                f"Year {year} complete: Imported {imported} records for {symbols} symbols with {errors} errors"
            ))

        # Final summary
        self.stdout.write(self.style.SUCCESS("\n" + "="*60))
        self.stdout.write(self.style.SUCCESS("FINAL IMPORT SUMMARY"))
        self.stdout.write(self.style.SUCCESS("="*60))
        self.stdout.write(f"Years processed: {years_processed}")
        self.stdout.write(f"Total records imported: {total_imported}")
        self.stdout.write(f"Total symbols processed: {total_symbols}")
        self.stdout.write(f"Total errors: {total_errors}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN: No data was actually saved to the database"))

    def _parse_year_range(self, year_spec):
        """Parse year specification like '2023' or '2001-2010' into list of years"""
        years = []

        if '-' in year_spec:
            start_year, end_year = map(int, year_spec.split('-'))
            if start_year > end_year:
                raise CommandError(f"Invalid year range: {year_spec}. Start year must be <= end year.")
            years = list(range(start_year, end_year + 1))
        else:
            years = [int(year_spec)]

        return years

    def _import_sequential(self, csv_files, import_path, year, skip_existing, dry_run):
        """Import files one by one"""
        total_imported = 0
        total_symbols = 0
        error_count = 0

        for csv_file in csv_files:
            symbol_name = csv_file.replace(f"_{year}.csv", "")
            filepath = os.path.join(import_path, csv_file)

            self.stdout.write(f"Processing {symbol_name} for year {year}...")

            imported, errors = self._process_file(
                symbol_name, filepath, year, skip_existing, dry_run
            )
            total_imported += imported
            error_count += errors
            total_symbols += 1

            self.stdout.write(f"  Imported {imported} records for {symbol_name} (errors: {errors})")

        return total_imported, total_symbols, error_count

    def _import_parallel(self, csv_files, import_path, year, workers, skip_existing, dry_run):
        """Import files in parallel for faster processing"""
        total_imported = 0
        total_symbols = 0
        error_count = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for csv_file in csv_files:
                symbol_name = csv_file.replace(f"_{year}.csv", "")
                filepath = os.path.join(import_path, csv_file)
                futures[executor.submit(
                    self._process_file, symbol_name, filepath, year, skip_existing, dry_run
                )] = symbol_name

            for future in as_completed(futures):
                symbol_name = futures[future]
                try:
                    imported, errors = future.result()
                    total_imported += imported
                    error_count += errors
                    total_symbols += 1
                    self.stdout.write(f"Completed {symbol_name}: {imported} records (errors: {errors})")
                except Exception as e:
                    self.stderr.write(f"Error processing {symbol_name}: {str(e)}")
                    error_count += 1

        return total_imported, total_symbols, error_count

    def _process_file(self, symbol_name, filepath, year, skip_existing, dry_run):
        """Process a single CSV file"""
        imported = 0
        errors = 0

        # Get or create symbol (always create even in dry run for counting)
        symbol, created = Symbol.objects.get_or_create(
            ticker=symbol_name,
            defaults={'company_name': symbol_name, 'is_active': True}
        )

        if dry_run:
            # In dry run mode, just count records without saving
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        if self._validate_row(row, year):
                            imported += 1
                    except Exception as e:
                        errors += 1
        else:
            # Actual import with database writes
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)

                # Use transaction for each file
                with transaction.atomic():
                    for row in reader:
                        try:
                            result = self._process_row(symbol, row, year, skip_existing)
                            if result:
                                imported += 1
                        except Exception as e:
                            self.stderr.write(f"Error in {symbol_name} row {row.get('date', 'unknown')}: {str(e)}")
                            errors += 1

        return imported, errors

    def _validate_row(self, row, year):
        """Validate a row without saving to database"""
        # Parse date
        date_str = row['date']
        if ' ' in date_str:
            row_date = datetime.strptime(date_str.split()[0], "%Y%m%d").date()
        else:
            row_date = datetime.strptime(date_str, "%Y%m%d").date()

        # Check if year matches
        if row_date.year != year:
            return False

        # Validate required fields exist
        required_fields = ['open', 'high', 'low', 'close', 'volume']
        for field in required_fields:
            if field not in row:
                raise ValueError(f"Missing required field: {field}")

        return True

    def _process_row(self, symbol, row, year, skip_existing):
        """Process a single CSV row"""
        # Parse date
        date_str = row['date']
        if ' ' in date_str:
            # Format like "20231101 09:30:00" - take just the date part
            row_date = datetime.strptime(date_str.split()[0], "%Y%m%d").date()
        else:
            # Format like "20231101"
            row_date = datetime.strptime(date_str, "%Y%m%d").date()

        # Skip if not the target year
        if row_date.year != year:
            return None

        # Parse volume - handle decimal values
        volume_str = row['volume'].strip()
        if '.' in volume_str:
            # Convert decimal string to float then to int
            volume = int(float(volume_str))
        else:
            volume = int(volume_str)

        # Parse price values
        open_price = Decimal(str(row['open']).strip())
        high_price = Decimal(str(row['high']).strip())
        low_price = Decimal(str(row['low']).strip())
        close_price = Decimal(str(row['close']).strip())

        # Check if record already exists (for skip_existing mode)
        if skip_existing:
            exists = DailyPrice.objects.filter(
                symbol=symbol,
                date=row_date
            ).exists()
            if exists:
                return None

        # Create or update record
        DailyPrice.objects.update_or_create(
            symbol=symbol,
            date=row_date,
            defaults={
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume,
            }
        )

        return True
